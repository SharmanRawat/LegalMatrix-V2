"""Field classifier — turns raw OCR lines into the 10 statutory fields.

Two backends:
  * LLMFieldClassifier — sends the OCR line list to a lightweight local model
    (default qwen2.5vl:3b via Ollama, pure-text task, ~1-3 s) which returns
    the fields plus the source line ids for each value.
  * RegexFieldClassifier — fully offline heuristic extraction (nice fallback
    when Ollama is down; the LLM is strictly better on product_name).

Both return the same shape:
  {
    "fields": {mrp, usp, net_quantity, product_name, manufacturer,
               manufacturing_date, expiry_date, consumer_care, dimensions, edible},
    "line_map": {field_key: [line_id, ...]},
    "engine": "llm"|"regex",
  }
"""
import hashlib
import json
import re
import time
from typing import Dict, List, Optional

import httpx

from app.config import FIELD_CLASSIFIER_MODEL, OLLAMA_HOST

FIELDS = [
    "mrp", "usp", "net_quantity", "product_name", "manufacturer",
    "manufacturing_date", "expiry_date", "consumer_care", "dimensions", "edible",
]

_MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC"

CLASSIFIER_PROMPT = (
    "You are a legal-metrology label parser. Below are OCR text lines read "
    "from a product label image. Each line is 'id=<id> text=\"...\"' followed "
    "by its pixel box [x1,y1,x2,y2].\n\n"
    "OCR text is machine-read, so it can be FRAGMENTED: one line may hold two "
    "values (e.g. '\u20b947.00\u20b90.24 Per 9' = two rupee prices; "
    "'07 / 04 / 26 06 / 04 / 27' = two dates), words may be joined without "
    "spaces, a '9' may really be a lowercase 'g', and the rupee symbol may "
    "render weirdly. Recover what a human would read from the label.\n\n"
    "Extract the following fields VERBATIM where printed, otherwise infer from "
    "context (date pairs are usually the manufacturing date first, then the "
    "expiry date): mrp, usp, net_quantity, product_name, manufacturer, "
    "manufacturing_date, expiry_date, consumer_care, dimensions, edible.\n"
    "Also return 'line_ids' as a JSON object mapping each field to the integer "
    "line id(s) where its printed text was found (empty array if absent).\n"
    "- edible: exactly \"yes\", \"no\", or \"\" (food/beverage/medicine => yes).\n"
    "- mrp: the maximum retail price with currency (e.g. \"MRP Rs. 265/-\" or "
    "\"\u20b947.00\"); pick the FIRST rupee price when several appear. Output "
    "a value ONLY when it sits next to an explicit MRP / M.R.P / Max Retail "
    "Price keyword or carries a currency symbol (\u20b9, Rs., INR). NEVER "
    "output a bare number with no currency and no 'MRP' word.\n"
    "- consumer_care: ONLY the printed consumer-complaint contact — email, "
    "toll-free or phone number (e.g. 'care@brand.com', 'TEL:1800-xxx'). "
    "Ignore slogans, disclaimers like 'All pictures shown are for "
    "illustration', addresses, license numbers and packaging lines.\n"
    "- dimensions: ONLY physical product dimensions with units (e.g. 'L 25cm "
    "x W 12cm'). Ignore packaging-material codes (HDPE, LDPE, PP, PET, cap, "
    "pourer, recycling symbols) — those are NOT dimensions.\n"
    "- usp: only a unit sale price that states a per-unit rate (e.g. 'USP Rs. "
    "0.24 per g', 'Rs. 5.89/100g'); it must contain 'per' or '/' plus a unit "
    "(g, ml, kg, l). Never invent the per-unit rate from the MRP alone.\n"
    "Verbatim rule: for mrp, usp, net_quantity, manufacturing_date, "
    "expiry_date and consumer_care output EXACTLY the printed text (fixing "
    "only OCR typos); never add digits, symbols or words that are not "
    "printed.\n"
    "- manufacturing_date / expiry_date: use MMM/YYYY, MM/YYYY or DD/MM/YY "
    "as printed; if the two dates sit in one line, assign them in "
    "MFG-then-EXP order.\n"
    "Respond with STRICT JSON only, no markdown, no commentary, exactly:\n"
    '{"mrp":"","usp":"","net_quantity":"","product_name":"","manufacturer":"",'
    '"manufacturing_date":"","expiry_date":"","consumer_care":"","dimensions":"",'
    '"edible":"","line_ids":{}}'
)


def _parse_json(raw: str) -> Optional[Dict]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{[\s\S]*\}", raw)
    if brace:
        try:
            return json.loads(brace.group())
        except json.JSONDecodeError:
            pass
    return None


def _empty_fields() -> Dict:
    return {k: "" for k in FIELDS}


def _clean_date_str(s: str) -> str:
    """Normalize '10 / 08 / 26' -> '10/08/26', 'SEP / 2025' -> 'SEP/2025'."""
    s = str(s or "").strip()
    return re.sub(r"\s*([/.\-])\s*", r"\1", s)


# Words never part of a product/brand name: label plumbing, names, addresses.
_PRODUCT_NAME_STOP = {
    "a", "an", "the", "of", "and", "for", "by", "net", "netwt", "netqty",
    "mrp", "rs", "incl", "all", "taxes", "fssai", "fsai", "batch", "no",
    "mfg", "mfd", "exp", "pkd", "mfgd", "lic", "made", "in", "india",
    "ingredients", "ingredient", "nutritional", "information", "storage",
    "storageadvice", "preparation", "serving", "size", "approximately",
    "approx", "values", "energy", "protein", "carbohydrate", "carbohydrates",
    "sugar", "sugars", "total", "fat", "cholesterol", "sodium", "fiber",
    "dietary", "mono", "unsaturated", "saturated", "poly", "trans",
    "protein", "vitamin", "calcium", "iron", "to", "not", "be", "consumed",
    "this", "product", "is", "sell", "before", "best", "use", "by", "date",
    "packed", "packing", "marketed", "manufactured", "customer", "care",
    "contact", "please", "for", "feedback", "suggestions", "executive",
    "address", "road", "street", "lane", "district", "state", "pincode",
    "follow", "food", "foods", "consumer", "complaints", "toll", "free",
    "website", "email", "phone", "lic", "licno", "suggestions", "imported",
    "distributed", "exported", "owner", "brand", "brandowner", "regd",
    "registered", "trademark", "proprietor", "keeps", "store", "home",
    # Address / geography (kills fake product names like "Sarkhej-Bavla Highway")
    "dist", "tal", "at", "b/h", "opp", "behind", "near", "highway",
    "nagar", "colony", "venue", "school", "complex",
    "gujarat", "mumbai", "delhi", "newdelhi", "maharashtra",
    "karnataka", "uttarakhand", "andhra", "chennai", "punjab", "haryana",
    "up", "rajasthan", "kerala", "tamil", "telangana", "westbengal",
    "anand", "sonipat", "panipat", "roorkee", "noida", "bhiwandi",
    "vilage", "village", "thsil", "saint", "a/c",
    "school", "opposite",
    "indore", "ghaziabad", "lucknow", "jaipur", "patna", "raipur",
    # Neighborhoods / estates / office-park fragments that leak from the
    # manufacturer address into product_name (OCR keeps the pincode on the
    # same line, e.g. 'Fnundation School,Powai,Mumbai,Pin-400076,Maharasha').
    "fnundation", "foundation", "powai", "hiranandani", "park",
    "industrial", "avenue", "factory", "estate", "marol", "vithal", "wadi",
    "maharasha", "maharastra", "maharasthra", "andheri", "goregaon", "ghatkopar",
    "pin", "pincode", "office", "works", "plot", "sector",
    # Boilerplate / warnings / hygiene text
    "images", "representation", "purpose",
    "allergen", "note", "contains", "may", "traces", "warning",
    "indulge", "yourself", "naturally",
    "bestbefore", "twelve", "twentyfour", "monthsfrom",
    "cool", "dry", "refrigerate", "protectiveatmosphere",
    "litter", "keepyourcityclean", "packaged", "dono", "litter",
    "max", "retail", "price", "inclusive", "taxes",
    "pourer", "label", "cap", "lid", "closure",
    "fatty", "acid", "monounsaturated", "polyunsaturated",
    "countryof", "origin", "benefits", "support",
    "taste", "delicious", "enjoy", "savour", "savor", "home",
    "origin", "made", "prepared", "served",
    "process", "processing", "company", "mission",
    "certified", "iso", "export", "import",
    "below", "above", "onc", "please", "read",
    "thal", "nut", "refrigerate",
}


# Substring fragments that mark a token as nutrition-table / packaging /
# claim / boilerplate text rather than a product name.  OCR glues whole
# phrases into one token (e.g. 'BESTBEFORETWENTYFOUR', 'MONTHSFROMPACKAGING',
# 'CRYSTALIZATIONOFHONEYIS'), so a plain stopword lookup never matches — the
# fragment must be matched anywhere inside the token.
_PRODUCT_TOKEN_FRAGS = (
    "NUTRITION", "INGREDIENT", "CARBOHYDRATE", "CHOLESTEROL",
    "PROTEIN", "FIBRE", "FIBER", "SUGARS", "SODIUM", "VITAMIN", "CALCIUM",
    "IRON", "ENERGY", "KCAL", "SERVING", "SERVE", "RDA", "CONTRIBUTION",
    "TYPICAL", "PACKAGING", "STORAGE", "REFRIGERATE", "PRESERVATIVE",
    "PRESERVATIV", "TRANSFAT", "COLOUR", "COLOR", "GLUTEN", "VEGETARIAN",
    "CRYSTAL", "PHENOMENON", "PACKED", "FSSAI", "BATCH", "BESTBEFORE",
    "MONTHSFROM", "TWENTYFOUR", "TWELVE", "CUSTOMER", "COMPLAINT",
    "FEEDBACK", "EXECUTIVE", "TOLL", "WEBSITE", "EMAIL", "APPROX",
    "VALUES", "CRIED", "MATTWINE", "MANTINUE", "RAWCODE", "CONSUMER",
    "ALLEGED", "CLAIM", "GUARANTEE", "FREEZER", "PRECISION",
    "INFORMATION", "FORMATION", "RECOMMENDED", "ALLOWANCE", "DIETARY",
    "HIGHWAY", "COMPOUND", "COMPOU", "COUNTRY", "ORIGIN", "BRAND",
)

# Whole-word blocks for tokens that fragment-matching would over-trigger on
# (e.g. 'LIC', 'CARE', 'IRON' as substrings appear inside brandable words).
_PRODUCT_WORD_BLOCKS = {
    "mfg", "mfd", "pkd", "exp", "best", "before", "months", "from", "lic",
    "care", "phone", "contact", "visitus",
    "weight", "net", "condition",
    "road", "street", "nagar", "highway", "sector", "village", "thsil",
    "taluka", "dist", "post", "mile", "stone", "p.o", "po", "pin", "kharsa",
    "plot", "factory", "estate", "colony", "chowk", "metro", "phase",
    "industrial", "works", "office", "gram", "mohalla",
    "ltd", "pvt", "rep", "repacked", "re-packed", "re-pack", "packed",
    "unit", "units", "by",
}

# An address-recital line (locality + road markers) is never a product name.
# 'Ninth Mile Stone Post Dujana Bulandshahar' is OCR glue from the backpanel
# address; kill the whole line once these markers appear. Company/address
# fragments (PVT, LTD, FLR, WING, WALL ST) mark importer-address continuation
# lines that the manufacturer matcher leaves unclaimed.
_ADDRESS_LINE_RE = re.compile(
    r"\b(?:mile\s*stone|stone\s*post|p\.?\s*o\.?\s*(?:box)?|kharsa|"
    r"post\s+office|village|taluka|thsil|tehsil|dist|po\s*[-\d]|"
    r"nagar|highway|sector[-\s]*\d+|wall\s*st|flr|wing|"
    r"\bpvt\b|\bltd\b|business\s*cnt|imported\s*by|manufactured\s*by)\b",
    re.IGNORECASE,
)


def _is_title_token(tok: str) -> bool:
    tok = tok.strip(".#,()[]-'\u2019")
    if not tok or len(tok) < 3 or len(tok) > 20 or any(ch.isdigit() for ch in tok):
        return False
    if tok.lower() in _PRODUCT_NAME_STOP:
        return False
    upper = tok.upper()
    if any(frag in upper for frag in _PRODUCT_TOKEN_FRAGS):
        return False
    if tok.lower() in _PRODUCT_WORD_BLOCKS:
        return False
    return tok[0].isupper() or tok.isupper()


# Company suffixes / address-y fragments stripped off extracted manufacturer
# names.  Keeps 'AVENUESUPERMARTSLTD.' clean vs the licence-noise that OCR
# often glues right after the company name.
_COMPANY_TRAIL_TRIM_RE = re.compile(
    r"[\s,]*(?:\([^)]*\)|\[[^\]]*\]|,?\.?$)", re.I
)
_COMPANY_STOP = {
    "fssai", "fsai", "india", "ind", "mumbai", "delhi", "newdelhi",
    "address", "lic", "no", "mfg", "mfd", "exp", "pkd", "best", "before",
}

# Label vocabulary for edibility verdicts. A 'yes' needs a food word on the
# label; a 'no' needs an explicit non-edible marker — otherwise the verdict
# is unverifiable (an SLM guessing 'no' on a nutrition table is not evidence).
_FOOD_WORDS_RE = re.compile(
    r"\b(food|beverage|drink|bonbon|chocolat|candy|biscuit|cookie|snack|spice|"
    r"masala|oil|olive|butter|cheese|cream|juice|milk|tea|coffee|coffe|noodle|"
    r"rice|dal|paneer|sauce|jam|honey|pickle|toothpaste|shampoo|soap|detergent|"
    r"soap it|tablet|capsule|syrup|gel|cream|lozenge|powde|solube|clove|cloves|"
    r"laung|laung?|lawang|cassia|worksanacceye|methyl|ethyl|salicylate|"
    r"eucalyptus)\b",
    re.IGNORECASE,
)
_NO_WORDS_RE = re.compile(
    r"\b(non.?edible|not for consumption|for external|cleanser|faucet)\b",
    re.IGNORECASE,
)


def _leading_number(value: str) -> Optional[float]:
    """First number in a price/quantity string ('MRP Rs. 599.00' -> 599.0).

    Used to reject zero declarations: no legal MRP, USP or net quantity is
    zero, so a '0' / '0 g' / 'Rs. 0.00' read is always OCR/SLM noise (usually
    a nutrition-table row)."""
    m = re.search(r"(\d+(?:\.\d+)?)", str(value or ""))
    return float(m.group(1)) if m else None


def edible_supported(value: str, lines: List[Dict]) -> bool:
    """Check an edibility verdict against the OCR text (see _FOOD_WORDS_RE)."""
    v = (value or "").strip().lower()
    joined = " ".join(str(line.get("text", "") or "") for line in lines)
    if v in ("yes", "true", "1", "y", "edible"):
        return bool(_FOOD_WORDS_RE.search(joined))
    if v in ("no", "false", "0", "n", "non_edible", "non-edible", "non edible"):
        return bool(_NO_WORDS_RE.search(joined))
    return True


def _strip_company(name: str) -> str:
    name = _COMPANY_TRAIL_TRIM_RE.sub("", name).strip()
    # OCR often prefixes the company with its licence tag
    # ('fssai Patanjali Foods Linmited').
    name = re.sub(r"^(?:fssai|fsai|lic\.?|lic\s*no\.?)\s+", "", name, flags=re.IGNORECASE)
    # Trailing standalone numbers are batch/pin codes glued by OCR
    # ('DEA 789', 'ABC FOODS 400093'), never part of the company name.
    name = re.sub(r"\s+\d[\d\s,./-]*$", "", name).strip()
    # The trailer-trim above removes parentheticals and can glue the company
    # suffix to the previous word ('Swabs () Ltd.' -> 'SwabsLtd.'), which
    # defeats token matching vs 'Swabs (I) Ltd.'. Split glued suffixes back
    # off — company suffixes are never part of the legal name word. Iterated
    # so nested chains ('NirmaPvtLtd') unwind layer by layer.
    glue = re.compile(
        r"(?<=[A-Za-z])(?=(?:Ltd|Limited|Pvt|Private|Inc|LLP|LLC)\b)",
        re.IGNORECASE,
    )
    prev = None
    while name != prev:
        prev = name
        name = glue.sub(" ", name)
    name = re.sub(r"\s{2,}", " ", name)
    if name.lower() in _COMPANY_STOP or len(name) < 3:
        return ""
    return name


# OCR glues address words together ('Parkadarthaakaroad'), defeating
# word-boundary matching — so product-name candidates are screened for
# address FRAGMENTS. Two distinct hits are required: a single hit keeps real
# names like 'Park Avenue' or 'Imported Extra Virgin Olive Oil' alive, while
# a glued address recital ('Herbal Park ... Laksar Road ...') trips several.
_NAME_ADDRESS_FRAGS = (
    "ROAD", "STREET", "NAGAR", "VILLAGE", "PARK", "MUMBAI", "HIGHWAY",
    "CHAMBERS", "PINCODE", "HERBAL", "LIMITED", "IMPORTED", "COLONY",
    "DISTRICT", "TALUKA", "UTTARAKHAND", "HARYANA", "MAHARASHTRA",
    "MANAGER", "MARKETING", "CONTACT",
)


def _looks_like_address(value: str) -> bool:
    upper = (value or "").upper()
    return sum(1 for frag in _NAME_ADDRESS_FRAGS if frag in upper) >= 2


class LLMFieldClassifier:
    def __init__(self, model: Optional[str] = None, timeout: float = 60.0):
        self.model = model or FIELD_CLASSIFIER_MODEL
        self.ollama_url = (OLLAMA_HOST or "http://localhost:11434").rstrip("/") + "/api/chat"
        self.timeout = timeout

    def prompt_fingerprint(self) -> str:
        return hashlib.sha256(CLASSIFIER_PROMPT.encode("utf-8")).hexdigest()

    def classify(self, lines: List[Dict]) -> Dict:
        if not lines:
            return {"fields": _empty_fields(), "line_map": {}, "engine": "llm", "error": "no_lines"}

        rendered = "\n".join(
            f'id={i} text="{_clip(line.get("text", ""))}" box=[{_box_str(line.get("box"))}]'
            for i, line in enumerate(lines)
        )
        user = f"{CLASSIFIER_PROMPT}\n\nOCR LINES:\n{rendered}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": 0.0, "num_ctx": 8192},
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.ollama_url, json=payload)
            if resp.status_code != 200:
                return self._fallback_error(f"ollama_http_{resp.status_code}")
            raw = resp.json().get("message", {}).get("content", "") or ""
            parsed = _parse_json(raw)
            if not parsed:
                return self._fallback_error("unparseable")
            return self._normalize(parsed)
        except Exception as e:
            return self._fallback_error(str(e))

    @staticmethod
    def _normalize(parsed: Dict) -> Dict:
        fields = _empty_fields()
        for key in FIELDS:
            value = parsed.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip() and str(value) != "None":
                fields[key] = str(value).strip()
        line_map = {}
        raw_map = parsed.get("line_ids") or {}
        if isinstance(raw_map, dict):
            for fkey, ids in raw_map.items():
                if isinstance(ids, (list, tuple)):
                    line_map[str(fkey)] = [int(i) for i in ids if isinstance(i, (int, float))]
        return {"fields": fields, "line_map": line_map, "engine": "llm"}

    @staticmethod
    def _fallback_error(reason: str) -> Dict:
        return {"fields": _empty_fields(), "line_map": {}, "engine": "llm", "error": reason}


def _clip(text: str, limit: int = 200) -> str:
    text = (text or "").replace('"', "'")
    return text[:limit]


def _box_str(box) -> str:
    if not box or len(box) != 4:
        return "0,0,0,0"
    return ",".join(str(int(v)) for v in box[:4])


class RegexFieldClassifier:
    _CURRENCY_GLYPH_FIX = {"于": "₹", "¥": "₹", "天": "₹", "舌": "₹", "曰": "₹", "元": "₹"}

    def classify(self, lines: List[Dict]) -> Dict:
        fields = _empty_fields()
        line_map: Dict[str, List[int]] = {k: [] for k in FIELDS}
        texts = [
            "".join(self._CURRENCY_GLYPH_FIX.get(ch, ch) for ch in str(line.get("text", "") or "").strip())
            for line in lines
        ]

        def take(key: str, value: str, ids: List[int]) -> None:
            value = value.strip()
            if not value or fields.get(key):
                return
            fields[key] = value
            line_map[key] = ids

        def match_line(text: str, ids: List[int], pairs_ok: bool = False) -> None:
            if not text:
                return
            mrp = self._match_mrp(text)
            take("mrp", mrp, [ids[0]])
            mfg, exp = self._extract_dates(text)
            take("manufacturing_date", mfg, [ids[0]])
            take("expiry_date", exp, [ids[0]])
            nq = self._match_net_quantity(text)
            take("net_quantity", nq, [ids[0]])
            manu = self._match_manufacturer(text)
            take("manufacturer", manu, [ids[0]])
            care = self._match_consumer_care(text)
            take("consumer_care", care, [ids[0]])
            dim = self._match_dimensions(text)
            take("dimensions", dim, [ids[0]])
            usp = self._match_usp(text)
            take("usp", usp, [ids[0]])

        for i, text in enumerate(texts):
            match_line(text, [i])

        for i in range(len(texts) - 1):
            joined = f"{texts[i]} {texts[i + 1]}"
            match_line(joined, [i, i + 1], pairs_ok=True)

        # consumer_care override: the per-line matcher emits at most one
        # contact, dropping non-1800 phones and phone+email pairs. Always
        # rebuild care from ALL printed channels (union, reading order).
        care = self._collect_care(texts)
        if care:
            fields["consumer_care"] = care
            line_map["consumer_care"] = [
                i for i, t in enumerate(texts)
                if re.search(r"@[\w.-]+\.[A-Za-z]{2,}|\d[\s\-()]?\d", t)
            ]

        if not fields["mrp"] or not fields["usp"]:
            mrp_val, usp_val, mrp_ids, usp_ids = self._match_sticker_prices(
                texts, fields.get("net_quantity", "")
            )
            if mrp_val:
                take("mrp", mrp_val, mrp_ids)
            if usp_val:
                take("usp", usp_val, usp_ids)

        if not fields["manufacturing_date"] or not fields["expiry_date"]:
            mfg_year, exp_year, mfg_ids, exp_ids = self._match_bare_year_dates(
                texts, fields.get("manufacturing_date", ""),
                fields.get("expiry_date", ""),
            )
            if mfg_year:
                take("manufacturing_date", mfg_year, mfg_ids)
            if exp_year:
                take("expiry_date", exp_year, exp_ids)
            # Reading-order repair: labels print MFG above EXP, so when the
            # month print survived for only ONE date and a bare year sits on
            # an earlier line (tiny 'JUL' lost, '2026' kept), the month-date
            # belongs to expiry, not manufacturing.
            if (fields.get("manufacturing_date") and not fields.get("expiry_date")
                    and re.search(
                        r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)",
                        fields["manufacturing_date"], re.IGNORECASE)):
                mfg_line = (line_map.get("manufacturing_date") or [10 ** 6])[0]
                bare = [(i, t) for i, t in enumerate(texts)
                        if self._BARE_YEAR_RE.match(t or "") and i < mfg_line]
                if bare:
                    fields["expiry_date"] = fields["manufacturing_date"]
                    line_map["expiry_date"] = line_map["manufacturing_date"]
                    fields["manufacturing_date"] = self._BARE_YEAR_RE.match(
                        bare[-1][1]).group(1)
                    line_map["manufacturing_date"] = [bare[-1][0]]

        if not fields["net_quantity"]:
            candidates = self._bare_net_quantities(lines)
            if candidates:
                best = self._pick_net_candidate(candidates, lines)
                take("net_quantity", best[0], [best[1]])

        # A zero MRP / USP / net quantity is never a valid declaration —
        # it is always a nutrition-table row ('0g') or a mangled sticker
        # read, so drop it rather than shipping it as a statutory value.
        for key in ("mrp", "usp", "net_quantity"):
            if fields.get(key) and (_leading_number(fields[key]) == 0.0):
                fields[key] = ""
                line_map[key] = []

        self._fill_edible(lines, fields)
        self._match_product_name(lines, fields, line_map, texts)
        return {"fields": fields, "line_map": line_map, "engine": "regex"}

    @staticmethod
    def _match_mrp(text: str) -> str:
        m = re.search(
            r"(?:M\.?\s*R\.?\s*P|MAX(?:IMUM)?\.?\s*RETAIL\s*PRICE)\s*[\s:.\-]*"
            r"(Rs\.?|INR|₹)?\s*(\d[\d,]*(?:\.\d+)?)\s*(/-)?",
            text, re.IGNORECASE,
        )
        if m:
            prefix = m.group(1) or "Rs."
            out = f"MRP {prefix} {m.group(2)}/"
            return out
        m2 = re.search(
            r"(?<![A-Za-z])(Rs\.?|INR|₹)\s*(\d[\d,]*(?:\.\d+)?)",
            text, re.IGNORECASE,
        )
        if m2:
            return f"MRP {m2.group(1)} {m2.group(2)}/"
        m3 = re.search(
            r"(?<![A-Za-z0-9.₹,])(\d[\d,]*(?:\.\d+)?)\s+(?:MRP|M\.?R\.?P)\s*$",
            text, re.IGNORECASE,
        )
        if m3:
            return f"MRP Rs. {m3.group(1)}/"
        return ""

    @staticmethod
    def _match_net_quantity(text: str) -> str:
        # OCR often splits 'NET QTY.: 250 ml (228 g)' across two boxes and
        # duplicates the leading digit ('NETQTY.:2' + '250 ml (228 g)'), so a
        # short stray number right after the keyword is skipped.
        m = re.search(
            r"(?:NET\s*(?:WT|QTY|QUANTITY|CONTENT|MASS)\.?\s*[:.]?\s*(?:\d{1,2}\s+)?)"
            r"([\d.,]+\s*(?:g|kg|gm|mg|ml|cl|L|l|litre|liter|mcm|m|cm|mm|pc|pcs|pieces?|no\.?)\b"
            r"(?:\s*\(\s*[\d.,]+\s*(?:g|kg|gm|mg|ml|cl|L|l|litre|liter)\s*\))?)",
            text, re.IGNORECASE,
        )
        return m.group(1) if m else ""

    @staticmethod
    def _match_dimensions(text: str) -> str:
        m = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(?:[xX×*]\s*|\s*b[yY]\s*)\s*"
            r"(\d+(?:[.,]\d+)?)\s*(?:[xX×*]\s*|\s*b[yY]\s*)?\s*"
            r"(\d+(?:[.,]\d+)?)?\s*(cm|mm|cm\b|mm\b)",
            text, re.IGNORECASE,
        )
        if m:
            return m.group(0)
        return ""

    @staticmethod
    def _bare_net_quantities(lines: List[Dict]) -> List[tuple]:
        """Whole-line bare quantities (e.g. '45g') — candidates only, returned
        as (value, line_index).  Zero values are ignored, nutrition noise
        (mg/decimals like 73.75g, 8.97g, 4.5g) is rejected via a pack-size-style
        ending check (…0/…5/.00) and milligram rows are dropped entirely.
        A bare '100 g'/'100 ml' next to a 'Per 100 g' nutrition table is the
        table's reference row, not the declared net quantity, so it is removed
        when the label shows a per-100 nutrition block."""
        joined = " ".join(str(l.get("text", "") or "") for l in lines).lower()
        has_nutrition_100 = bool(
            re.search(r"\bper\s*100\s*(g|gm|ml|gms)\b|\b%rda\b|\bservings?\s*per", joined)
        )
        out = []
        for i, line in enumerate(lines):
            text = str(line.get("text", "") or "").strip()
            m = re.match(
                r"^(\d+(?:\.\d+)?)\s*(g|kg|gm|mg|ml|cl|L|l|litre|litres|liter|m|cm|mm)"
                r"(\s*\(\s*\d+(?:\.\d+)?\s*(?:g|kg|gm|mg|ml|cl|L|l|litre|litres|liter)\s*\))?"
                r"\s*\.?$",
                text, re.IGNORECASE,
            )
            if not m:
                continue
            num = m.group(1)
            num_v = float(num)
            unit = m.group(2).lower()
            parenthetical = m.group(3) or ""
            if num_v <= 0:
                continue
            if unit == "mg":
                continue
            if has_nutrition_100 and num_v == 100 and unit in ("g", "gm", "ml"):
                continue
            value = f"{num}{unit}{parenthetical}" if parenthetical else f"{num}{unit}"
            if unit in ("kg", "l", "litre", "litres", "liter"):
                out.append((value, i))
            elif num_v >= 10 and re.search(r"(?:\.0+|[05])$", num):
                out.append((value, i))
        return out

    @staticmethod
    def _pick_net_candidate(
        candidates: List[tuple], lines: List[Dict]
    ) -> tuple:
        """Pick the bare net-quantity candidate that sits next to a real
        'Net Quantity:' label, preferring integer pack sizes over the
        decimal rows of the nutrition table."""
        kw = re.compile(r"\b(net|netqty|netwt|quantity|qty|wt|weight|content)\b", re.I)
        kw_idx = [
            i for i, ln in enumerate(lines)
            if kw.search(str(ln.get("text", "") or ""))
        ]

        def score(item: tuple) -> tuple:
            value, idx = item
            dist = min((abs(idx - k) for k in kw_idx), default=10 ** 6)
            int_frac = 0 if re.fullmatch(r"\d+", re.sub(r"[^0-9.]", "", value)) else 1
            try:
                num = float(re.sub(r"[^0-9.]", "", value))
            except ValueError:
                num = 0.0
            return (dist, int_frac, -num)

        return min(candidates, key=score)

    @staticmethod
    def _match_date(text: str, kind: str) -> str:
        mfg, exp = RegexFieldClassifier._extract_dates(text)
        return mfg if kind == "manufacturing" else exp

    @staticmethod
    def _extract_dates(text: str):
        """Return ``(manufacturing_date, expiry_date)`` as printed, using label
        keywords (MFG/PKD/MD, EXP/BEST BEFORE) with month-name or numeric
        dates, then any keyword-less month/year pairs read left-to-right
        (first date = manufacturing, second = expiry)."""
        num_dt = r"\d{1,4}\s*[/.\-]\s*\d{1,2}(?:\s*[/.\-]\s*\d{2,4})?"
        months = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)"
        mon_dt = rf"(?:\d{{1,2}}\s*)?{months}(?:\s*[/.\-]?\s*\d{{2,4}}|\d{{2,4}})"
        date_alt = rf"(?:{mon_dt}|{num_dt})"

        mfg_kw = (
            r"\b(?:MFG|M\s*\.?\s*D\.?|MFD|MANUFACTUR\w*\s*(?:DATE|ON)?|"
            r"PKD|PKG\.?|PACK(?:ED|ING)?\s*DATE|DATE\s*OF\s*PACK(?:ING|AGING)?|"
            r"MONTH\s*OF\s*PACK(?:ING|AGING))\b\s*[:.\s-]*"
        )
        exp_kw = (
            r"\b(?:EXP(?:IRY)?\s*DATE|EXP|BEST\s*BEFORE|USE\s*BY|SELL\s*BY|"
            r"CONSUME\s*BEFORE|UEB?Y)\b\s*[:.\s-]*"
        )

        mfg = re.search(r"(" + mfg_kw + date_alt + r")", text, re.IGNORECASE)
        exp = re.search(r"(" + exp_kw + date_alt + r")", text, re.IGNORECASE)
        month_pairs = list(
            re.finditer(
                rf"(?<![A-Za-z0-9])(?:\d{{1,2}}\s*)?{months}\s*[/.\-]?\s*\d{{2,4}}",
                text, re.IGNORECASE,
            )
        )
        hints = []
        for m in (mfg, exp):
            if not m:
                continue
            raw = m.group(1)
            date_hit = re.search(
                r"(" + date_alt + r")\s*$", raw, re.IGNORECASE
            )
            if not date_hit:
                continue
            date_val = _clean_date_str(date_hit.group(1))
            kind = "mfg" if m is mfg else "exp"
            hints.append((date_val, kind, m.start()))
        for m in month_pairs:
            month = re.search(r"(?:[A-Z]{3})", m.group(0), re.IGNORECASE)
            y = re.search(r"(\d+)\s*$", m.group(0))
            if month and y:
                hints.append((f"{month.group(0).upper()}/{y.group(1)}", None, m.start()))
        hints.sort(key=lambda h: h[2])

        kw_months = {h[0].upper() for h in hints if h[1] is not None}
        mfg_date = next((h[0] for h in hints if h[1] == "mfg"), None)
        exp_date  = next((h[0] for h in hints if h[1] == "exp"), None)
        loose = [
            h[0] for h in hints if h[1] is None
            and all(not h[0].upper().endswith(k.split("/")[-1].upper())
                     for k in kw_months)
        ]
        if mfg_date is None and loose:
            mfg_date = loose[0]
        if exp_date is None and loose:
            if len(loose) >= 2 and mfg_date == loose[0]:
                exp_date = loose[1]
            elif len(loose) == 1 and mfg_date is None:
                exp_date = loose[0]
        return (mfg_date or ""), (exp_date or "")

    @staticmethod
    def _match_consumer_care(text: str) -> str:
        email = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        if email:
            return email.group(0)
        phone = re.search(r"\b1800[\s-]?\d{3}[\s-]?\d{3,}\b", text)
        if phone:
            return phone.group(0)
        return ""

    @staticmethod
    def _collect_care(texts: List[str]) -> str:
        """Union of ALL contact channels printed on the label, in reading order.

        The per-line matcher returns at most ONE email or ONE 1800 number, so a
        phone like '022-71230555' (no 1800) or a phone+email pair on one line
        was never emitted — the biggest single source of consumer_care losses.
        This pass collects every email, every toll-free, and every phone that
        is printed grouped (digits separated by space/hyphen/bracket, e.g.
        '022-71230555', '+91 9825588822', '91069 80469', '1800 103 1947') or
        sits on a contact-hint line ('TEL:', 'PHONE', 'CALL US', 'CARE',
        'TOLL-FREE'), which keeps bare barcode / FSSAI / batch digit-runs out.
        """
        contact_hints = ("TEL", "PHONE", "PH.NO", "PHNO", "CALL", "CARE",
                         "TOLL", "E-MAIL", "EMAIL", "@")
        # OCR often glues the printed 'E-MAIL:'/'TEL:' label onto the address
        # itself ('E-MAlldaburcares@dabur.com' from E-MAIL:DAUBURCARES@…),
        # so strip the label prefix from the local part when it appears glued.
        email_label_pfx = re.compile(
            r"^(?:e[-_. ]?ma?l{1,2}|mail)[.:_-]?", re.I)
        contacts: List[str] = []
        seen_digits: set = set()
        for t in texts:
            upper = t.upper()
            hinted = any(h in upper for h in contact_hints)
            hinted = hinted or bool(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", t))
            for em in re.finditer(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", t):
                val = em.group(0).lower()
                stripped = email_label_pfx.sub("", val)
                if stripped.split("@", 1)[0]:
                    val = stripped
                if val not in contacts:
                    contacts.append(val)
            for ph in re.finditer(r"\d[\d\s\-()]*\d", t):
                digits = re.sub(r"\D", "", ph.group(0))
                if not (len(digits) in (10, 11, 12) or digits.startswith("1800")):
                    continue
                # require a grouping separator OR a contact-hint line; a bare
                # digit run on a plain line is more likely barcode/batch/id.
                # Even with a separator, the first group must be phone-shaped
                # (2–6 digits): '280656485 8' from a date line is not one.
                first_seg = re.split(r"[\s\-()]+", ph.group(0))[0]
                if not (re.search(r"[\s\-()]", ph.group(0))
                        and 2 <= len(first_seg) <= 6):
                    if not (hinted or digits.startswith("1800")):
                        continue
                if digits in seen_digits:
                    continue
                seen_digits.add(digits)
                contacts.append(ph.group(0).strip())
        return ", ".join(contacts)

    @staticmethod
    def _match_manufacturer(text: str) -> str:
        m = re.search(
            r"(?:MANUFACTUR(?:ED|ING)?(?:\s*[&,]\s*PACK(?:ED|ING)?)?\s*(?:BY|AT)"
            r"|MARKETED\s*BY|MADE\s+IN|PACKED\s*BY|PACKED\s*AT|PROCESSED\s*[&,]\s*PACK(?:ED|ING)?\s*BY"
            r"|IMPORTED\s*BY|DISTRIBUTED\s*BY|M/s\.?)"
            r"\s*[:.]?\s*([A-Z][A-Za-z0-9&.,' -]+)",
            text, re.IGNORECASE,
        )
        if not m or not isinstance(m.group(1), str):
            return ""
        val = _strip_company(m.group(1).strip())
        if not val:
            return ""
        if len(val) < 4:
            return ""
        if re.match(r"^Per\s+\d+", val, re.IGNORECASE):
            return ""
        alnum = re.sub(r"[^A-Za-z]", "", val)
        if alnum and sum(c.islower() for c in alnum) / len(alnum) > 0.75:
            return ""
        bad_words = {"manufactur", "factory", "please", "character", "lic",
                     "no", "number", "address", "read", "see", "above",
                     "below", "first", "product", "batch", "this"}
        if any(w in val.lower().split() for w in bad_words):
            return ""
        return val

    @staticmethod
    def _match_usp(text: str) -> str:
        m = re.search(
            r"(?:USP|UNIT\s*SALE\s*PRICE)[^0-9]{0,6}(Rs\.?|INR|₹)?\s*([\d]+(?:\.\d+)?)\s*(?:per|/)\s*(g|ml|kg|l|litre|cm|m|pcs|pieces?|no\.?)",
            text, re.IGNORECASE,
        )
        if m:
            sym = m.group(1) or "Rs."
            return f"USP {sym} {m.group(2)}/{m.group(3)}"
        for pat_sym in (True, False):
            core = r"(\d+(?:\.\d+)?)\s*(?:per|/)\s*(\d+(?:\.\d+)?)?\s*(g|gm|kg|ml|l|litre|cm|m|pcs|pieces?|no\.?)(?!\w)"
            if pat_sym:
                pat = r"(?<![A-Za-z])(Rs\.?|INR|₹)\s*" + core
            else:
                pat = r"(?<![A-Za-z0-9.])(?:\bper\s*|/)?\s*(?<!\d)" + core
            m2 = re.search(pat, text, re.IGNORECASE)
            if m2:
                if pat_sym:
                    sym = m2.group(1) or "Rs."
                    group2 = m2.group(2)
                    group4 = m2.group(4)
                else:
                    sym = "Rs."
                    group2 = m2.group(1)
                    group4 = m2.group(3)
                return f"USP {sym} {group2}/{group4}"
        return ""

    # A bare decimal price line on the white batch/MRP sticker near the
    # barcode (e.g. '599.00' under 'JUL 2026 / JAN 2028'). Whole-line only,
    # so nutrition decimals ('73.75g') and barcode runs never match.
    _BARE_PRICE_RE = re.compile(r"^\s*(\d{2,5}\.\d{2})\s*$")
    # Lines that mark a batch sticker block: months, years, licence/batch
    # codes, date keywords. A bare price only counts when one of these is
    # within 3 lines — otherwise a stray number is not an MRP.
    _STICKER_CUE_RE = re.compile(
        r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC|20\d{2}|"
        r"Lic|batch|LOT|MFG|MFD|EXP|BEST|USE\s*BY|(?:^|(?<=\s))[A-Z]\d{3,}[A-Z0-9]*)",
        re.IGNORECASE,
    )

    # The ₹ after MRP often degrades to a stray letter ('MRPE'), and the
    # price itself sits lines away on the sticker — so the keyword is
    # detected separately from the value.
    _MRP_KEYWORD_RE = re.compile(
        r"(?<![A-Za-z])(?:M\s*\.?\s*R\s*\.?\s*P[E\u20b9]?|MAX(?:IMUM)?\s*RETAIL\s*PRICE)",
        re.IGNORECASE,
    )

    @staticmethod
    def _match_sticker_prices(texts: List[str], net_quantity: str) -> tuple:
        """Fallback MRP/USP from the batch sticker when OCR dropped the ₹
        glyph and no MRP keyword survived (tiny print near the barcode).

        Convention on Indian stickers: the largest bare decimal is the MRP,
        the smaller one the unit sale price. Returns
        (mrp, usp, mrp_ids, usp_ids), each possibly empty."""
        has_mrp_keyword = any(
            RegexFieldClassifier._MRP_KEYWORD_RE.search(t or "") for t in texts
        )
        cands: List[tuple] = []
        for i, text in enumerate(texts):
            m = RegexFieldClassifier._BARE_PRICE_RE.match(text or "")
            if not m:
                continue
            if has_mrp_keyword:
                cands.append((float(m.group(1)), m.group(1), i))
                continue
            window = " ".join(texts[max(0, i - 3): i + 4])
            if not RegexFieldClassifier._STICKER_CUE_RE.search(window):
                continue
            cands.append((float(m.group(1)), m.group(1), i))
        if not cands:
            return ("", "", [], [])
        cands.sort(key=lambda c: c[0], reverse=True)
        mrp_num, mrp_raw, mrp_idx = cands[0]
        mrp = f"MRP Rs. {mrp_raw}"
        usp = ""
        usp_ids: List[int] = []
        if len(cands) > 1:
            net_num, net_unit = RegexFieldClassifier._parse_net_for_usp(net_quantity)
            expected = (mrp_num / net_num) if net_num else None
            best, best_idx, best_err = None, cands[1][2], None
            for num, raw, idx in cands[1:]:
                readings = [num]
                dm = re.fullmatch(r"3(\d\.\d{2})", raw)
                if dm:
                    # ₹ is often misread as a leading '3' ('₹2.40' -> '32.40').
                    readings.append(float(dm.group(1)))
                if expected is not None:
                    reading = min(readings, key=lambda r: abs(r - expected))
                    err = abs(reading - expected)
                else:
                    reading, err = num, 0.0
                if best is None or err < best_err:
                    best, best_idx, best_err = reading, idx, err
            if expected is None or best_err <= 0.06:
                unit = f"/{net_unit}" if net_unit else ""
                usp = f"USP Rs. {best:.2f}{unit}"
                usp_ids = [best_idx]
        return (mrp, usp, [mrp_idx], usp_ids)

    @staticmethod
    def _parse_net_for_usp(net_quantity: str) -> tuple:
        m = re.search(
            r"(\d+(?:\.\d+)?)\s*(kg|g|gm|mg|ml|cl|l|litre|liter)\b",
            str(net_quantity or ""), re.IGNORECASE,
        )
        if not m:
            return (None, "")
        value = float(m.group(1))
        unit = m.group(2).lower()
        if unit == "kg":
            return (value * 1000, "g")
        if unit in ("l", "litre", "liter"):
            return (value * 1000, "ml")
        if unit in ("gm",):
            return (value, "g")
        if unit == "cl":
            return (value * 10, "ml")
        return (value, unit)

    _BARE_YEAR_RE = re.compile(r"^\s*(20\d{2})\s*$")
    _BATCH_CUE_RE = re.compile(
        r"(Lic|batch|LOT|MFG|MFD|PKD|EXP|BEST|(?:^|(?<=\s))[A-Z]\d{3,}[A-Z0-9]*)",
        re.IGNORECASE,
    )

    @staticmethod
    def _match_bare_year_dates(texts: List[str], mfg: str, exp: str) -> tuple:
        """Fallback when the month print is too small for OCR and only a bare
        year survives next to the batch code ('L66280' / '2026' under the real
        'JUL 2026'). The year closest to a batch cue becomes the manufacturing
        year; a second distinct year becomes expiry. Gated on cue proximity so
        stray years never invent dates."""
        if mfg and exp:
            return ("", "", [], [])
        known_years = set(re.findall(r"20\d{2}", f"{mfg} {exp}"))
        cands: List[tuple] = []
        for i, text in enumerate(texts):
            m = RegexFieldClassifier._BARE_YEAR_RE.match(text or "")
            if not m or m.group(1) in known_years:
                continue
            window = " ".join(texts[max(0, i - 3): i + 4])
            if not RegexFieldClassifier._BATCH_CUE_RE.search(window):
                continue
            dist = min(
                (abs(i - j) for j, t in enumerate(texts)
                 if RegexFieldClassifier._BATCH_CUE_RE.search(t or "")),
                default=99,
            )
            cands.append((dist, i, m.group(1)))
        if not cands:
            return ("", "", [], [])
        cands.sort()
        years = [(idx, yr) for _, idx, yr in cands]
        out_mfg, out_exp = "", ""
        out_mfg_ids, out_exp_ids = [], []
        if not mfg and years:
            out_mfg, out_mfg_ids = years[0][1], [years[0][0]]
        rest = [y for y in years[1:] if y[1] != (out_mfg or mfg.split("/")[-1])]
        if not exp and rest:
            out_exp, out_exp_ids = rest[0][1], [rest[0][0]]
        return (out_mfg, out_exp, out_mfg_ids, out_exp_ids)

    @staticmethod
    def _match_product_name(lines: List[Dict], fields: Dict, line_map: Dict,
                            texts: List[str]) -> str:
        """Heuristic brand/product name: the longest run of consecutive
        title-case words from the label that isn't already claimed by another
        field, isn't label plumbing, and ideally caps up with a net-quantity
        suffix (e.g. 'LAWANG-20g') for foods that print name+size on one line.
        If that front-panel run carries a size, the net_quantity value the
        caller already extracted is appended as ' -N g' so the product name
        matches the printed label (e.g. 'DMART Premia LAWANG - 20 g')."""
        used_ids = {i for ids in line_map.values() for i in ids}
        best_name, best_len = "", 0
        for i, text in enumerate(texts):
            if i in used_ids:
                continue
            toks = RegexFieldClassifier._product_tokens(text)
            if not toks:
                continue
            name = " ".join(toks)
            if len(name) < 4:
                continue
            # Address-recital runs are never product names, even when the
            # manufacturer matcher left the line unclaimed. The fragment
            # screen catches OCR-glued recitals ('Parkadarthaakaroad') that
            # word-boundary matching misses.
            if _ADDRESS_LINE_RE.search(text):
                continue
            if _looks_like_address(name):
                continue
            # A run consisting only of company/legal suffixes or licence words
            # ('LIMITED', 'PVT', 'INDIA', 'FSSAI') is not a product name.
            words = [w.lower().rstrip(".,") for w in toks]
            if words and not any(
                w not in {"limited", "ltd", "pvt", "private", "inc", "co",
                          "india", "corporation", "asso", "proprietor"} for w in words
            ):
                continue
            score = len(name) if not re.search(r"\d", name) else len(name) * 1.2
            if score > best_len:
                best_len = score
                best_name = name

        # Front brand block: consecutive product-ish lines at the top of the
        # label (before any date/licence/ingredients plumbing) are joined, e.g.
        # 'DAMart' + 'Premia' + 'LAWANG-20g' -> 'DAMart Premia LAWANG 20g'.
        front = []
        for i, text in enumerate(texts):
            if i in used_ids:
                break
            if _ADDRESS_LINE_RE.search(text):
                continue
            toks = RegexFieldClassifier._product_tokens(text)
            if not toks:
                break
            for t in toks:
                if front and t == front[-1]:
                    continue
                front.append(t)
        if front:
            name = " ".join(front)
            score = len(name)
            if len(front) >= 2 and score > best_len * 0.9:
                best_name = name
                best_len = score

        if best_name and re.search(r"\d", best_name) and fields.get("net_quantity"):
            nq = re.sub(r"\s+", "", fields["net_quantity"])
            if nq not in best_name.replace(" ", ""):
                best_name = f"{best_name} {nq}"
        if best_name:
            fields["product_name"] = best_name
            line_map["product_name"] = [
                i for i, t in enumerate(texts) if best_name.split()[0] in t
            ]
        return best_name

    @staticmethod
    def _product_tokens(text: str) -> List[str]:
        """Title-case/product tokens from one line, splitting glued name+size
        like 'LAWANG-20g' into ('LAWANG', '20g') and dotted junk
        ('Approx.Values' -> 'Approx', 'Values', both stopwords)."""
        if not text:
            return []
        if re.search(
            r"\b(?:per\s*100\s*g|approx\.?|approx\.?\s*values|servings?\s*per\s*package|"
            r"nutrition\s*facts|energy\s*per|per\s*serving|typical\s*values)\b",
            text, re.IGNORECASE,
        ):
            return []
        # Address lines carry a pincode glued to the locality (e.g.
        # 'Fnundation School,Powai,Mumbai,Pin-400076,Maharasha') or are a pure
        # locality recital ('Ninth Mile Stone Post Dujana Bulandshahar') —
        # never a product name. Kill the whole line once pin/address markers
        # show up. Factory-address lines ('N-IV, KM 388, 14610. ALCOLEA')
        # carry road-distance codes plus multi-digit numbers — also never a
        # name, while real name+size prints ('LAWANG-20g') stay under 100.
        if re.search(r"\b(?:pin|pincode|)-?\s*\d{6}\b", text, re.IGNORECASE):
            return []
        if _ADDRESS_LINE_RE.search(text):
            return []
        if re.search(r"\b\d{5,}\b", text):
            return []
        if re.search(r"\bKM\b", text, re.IGNORECASE) and re.search(
            r"\b\d{3,}\b", text
        ):
            return []
        # Storage-instruction recitals ('Store in a cool & dry place',
        # 'STOREIN COOL&DRY PLACE') are not product names.
        if "store" in text.lower() and re.search(
            r"\b(?:cool|dry|place|refrigerat|shade|room|humid|protect)\b",
            text, re.IGNORECASE,
        ):
            return []
        toks = []
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9&.'-]*|\d+(?:\.\d+)?\s*(?:g|kg|gm|ml|l|cm|mm|m)\b", text):
            for t in re.split(r"[./]", raw):
                t = t.strip(".-")
                if not t:
                    continue
                if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:g|kg|gm|ml|l|cm|mm|m)\b", t, re.IGNORECASE):
                    toks.append(t)
                    continue
                m = re.fullmatch(r"([A-Za-z][A-Za-z0-9&.'-]*?)-(\d+(?:\.\d+)?\s*(?:g|kg|gm|ml|l|cm|mm|m))\b", t, re.IGNORECASE)
                if m and _is_title_token(m.group(1)):
                    toks.append(m.group(1))
                    toks.append(m.group(2))
                    continue
                if _is_title_token(t):
                    toks.append(t)
        # A lone ultra-long ALL-CAPS blob ('HOWRAHWESTBENGL', 'IMPORTEDEXTRA')
        # is OCR-glued address/nutrition residue, never a brand name. Real
        # front-panel names are multi-token or short single brands.
        if len(toks) == 1 and len(toks[0]) >= 13 \
                and toks[0].isalpha() and toks[0].isupper():
            return []
        return toks

    @staticmethod
    def _fill_edible(lines: List[Dict], fields: Dict) -> None:
        joined = " ".join(str(l.get("text", "")) for l in lines)
        if _NO_WORDS_RE.search(joined):
            fields["edible"] = "no"
        elif _FOOD_WORDS_RE.search(joined):
            fields["edible"] = "yes"


def get_classifier(model: Optional[str] = None, force_regex: bool = False):
    if force_regex:
        return RegexFieldClassifier()
    return LLMFieldClassifier(model=model)
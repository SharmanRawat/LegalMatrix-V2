'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

export type Lang = 'en' | 'hi'

const STORAGE_KEY = 'lm_lang'

/**
 * Hindi (hi-IN) translations keyed by the English source string.
 * Missing keys fall back to the English source (harmless + robust).
 */
const HI: Record<string, string> = {
  // ---- Navbar / shared ----
  Dashboard: 'डैशबोर्ड',
  'New Inspection': 'नई जांच',
  History: 'इतिहास',
  'Sign out': 'साइन आउट',
  'Sign in': 'साइन इन करें',
  'Status:': 'स्थिति:',
  Status: 'स्थिति',
  'Model:': 'मॉडल:',
  Compliance: 'अनुपालन',

  // ---- Status names ----
  Compliant: 'अनुपालक',
  'Review required': 'समीक्षा आवश्यक',
  'Potential violation': 'संभावित उल्लंघन',

  // ---- Home / inspection entry ----
  'AI-Powered Legal Metrology Inspection': 'एआई-आधारित विधिक मेट्रोलॉजी जांच',
  'Capture or Upload Product Images': 'उत्पाद की छवियाँ कैप्चर करें या अपलोड करें',
  'Add photos per label type (up to {max} total · {added} added). The inspection routes each field to the right photo — product name from the front, declarations from the back.':
    'प्रत्येक लेबल प्रकार के अनुसार फ़ोटो जोड़ें (कुल {max} तक · {added} जोड़े गए)। जांच हर फ़ील्ड को सही फ़ोटो से जोड़ती है — उत्पाद का नाम सामने से, घोषणाएँ पीछे से।',
  'Capturing for:': 'इसके लिए फ़ोटो ली जा रही है:',
  Capture: 'फ़ोटो लें',
  Close: 'बंद करें',
  Upload: 'अपलोड करें',
  photo: 'फ़ोटो',
  photos: 'फ़ोटो',
  'Maximum {n} images allowed': 'अधिकतम {n} छवियाँ अनुमत',
  'Photo {n} captured for {label}': 'फ़ोटो {n} लिया गया: {label}',
  "Couldn't preview \"{name}\" (unsupported image format?)":
    '"{name}" का पूर्वावलोकन नहीं हो सका (असमर्थित छवि प्रारूप?)',
  'Please select or capture at least one image': 'कृपया कम से कम एक छवि चुनें या कैप्चर करें',
  'Inspection completed!': 'जांच पूर्ण हुई!',
  'Request timed out. The vision model can take several minutes.':
    'अनुरोध का समय समाप्त हो गया। विज़न मॉडल को कई मिनट लग सकते हैं।',
  'Failed to inspect images.': 'छवियों की जांच विफल रही।',
  'Vision-model inspection typically takes 1-3 min per image. The request is in flight.':
    'विज़न-मॉडल जांच में प्रति छवि आमतौर पर 1-3 मिनट लगते हैं। अनुरोध प्रगति पर है।',
  'I confirm all {n} photos show the same product being inspected.':
    'मैं पुष्टि करता/करती हूँ कि सभी {n} फ़ोटो एक ही उत्पाद दिखा रहे हैं।',
  'Required before analyzing — mixing photos of different products gives a misleading compliance score.':
    'विश्लेषण से पहले आवश्यक — अलग-अलग उत्पादों की फ़ोटो मिलाने से भ्रामक अनुपालन स्कोर मिलता है।',
  Analyzing: 'विश्लेषण हो रहा है',
  Analyze: 'विश्लेषण करें',
  'Confirm the photos show the same product, then analyze.': 'पुष्टि करें कि फ़ोटो एक ही उत्पाद दिखाती हैं, फिर विश्लेषण करें।',
  'Camera access denied. Use file upload instead.': 'कैमरा एक्सेस अस्वीकृत। इसके बजाय फ़ाइल अपलोड का उपयोग करें।',

  // ---- Label types ----
  'Front Label (PDP)': 'सामने का लेबल (PDP)',
  'Back Label (Declarations)': 'पीछे का लेबल (घोषणाएँ)',
  'Side Label': 'किनारे का लेबल',
  'Top / Cap Label': 'ऊपर / ढक्कन का लेबल',
  'Other Packaging': 'अन्य पैकेजिंग',
  'Brand face & product name — strongest source for the name': 'ब्रांड का मुख्य भाग और उत्पाद का नाम — नाम का सबसे मजबूत स्रोत',
  'MRP, net qty, manufacturer, dates, consumer care': 'एमआरपी, शुद्ध मात्रा, निर्माता, तिथियाँ, उपभोक्ता सेवा',
  'Side panel: nutrition / extra dates / care': 'किनारे का पैनल: पोषण / अतिरिक्त तिथियाँ / देखभाल',
  'Cap or roof face: batch no, use-by, MRP/USP (EVEREST-style packs)': 'ढक्कन या ऊपरी सतह: बैच संख्या, उपयोग-तिथि, एमआरपी/यूएसपी (EVEREST-शैली पैक)',
  'Seals, pack shots, barcodes': 'सील, पैक फ़ोटो, बारकोड',

  // ---- Field labels ----
  'Unit Sale Price': 'इकाई विक्रय मूल्य',
  MRP: 'एमआरपी',
  'Net Quantity': 'शुद्ध मात्रा',
  'Product Name': 'उत्पाद का नाम',
  Manufacturer: 'निर्माता',
  'Manufacturing Date': 'निर्माण तिथि',
  'Expiry Date': 'समाप्ति तिथि',
  'Consumer Care': 'उपभोक्ता सेवा',
  Dimensions: 'आयाम',
  'Edibility (food?)': 'खाद्यता (खाद्य?)',

  // ---- Results section ----
  'rules passed': 'नियम पारित',
  'Compliance Radar': 'अनुपालन रडार',
  'Axes weighed by legal impact (declarations 30%, pricing 20%, dates 10%, consumer care 10%, font size 20%, readability 10%). The font-size axis is excluded when no calibration reference (credit card / barcode) is present.':
    'अक्षों का भार कानूनी प्रभाव से तय होता है (घोषणाएँ 30%, मूल्य निर्धारण 20%, तिथियाँ 10%, उपभोक्ता सेवा 10%, फ़ॉन्ट आकार 20%, पठनीयता 10%)। जब कोई अंशांकन संदर्भ (क्रेडिट कार्ड / बारकोड) मौजूद न हो तो फ़ॉन्ट-आकार अक्ष बाहर रखा जाता है।',
  'Compliance Heat-Map': 'अनुपालन हीट-मैप',
  'Verdicts drawn back onto the photo — green = compliant, red = violation, yellow = low confidence, cyan = calibration reference.':
    'फैसले फ़ोटो पर अंकित किए गए हैं — हरा = अनुपालक, लाल = उल्लंघन, पीला = कम विश्वास, सियान = अंशांकन संदर्भ।',
  'Verdicts drawn onto each photo — green = compliant, red = violation, yellow = low confidence, cyan = calibration reference.':
    'फैसले प्रत्येक फ़ोटो पर अंकित किए गए हैं — हरा = अनुपालक, लाल = उल्लंघन, पीला = कम विश्वास, सियान = अंशांकन संदर्भ।',
  'Heat-map unavailable': 'हीट-मैप अनुपलब्ध',
  'Photo {n} heat-map': 'फ़ोटो {n} का हीट-मैप',
  'Extracted Declarations': 'निष्कर्षित घोषणाएँ',
  'Extraction confidence': 'निष्कर्षण विश्वास',
  'required fields': 'आवश्यक फ़ील्ड',
  'Click the pencil icon to correct a misread value. Saving re-runs the compliance check and score immediately, and the correction is stored with the inspection (original AI value kept for audit).':
    'गलत पढ़े गए मान को सुधारने के लिए पेंसिल आइकन पर क्लिक करें। सहेजने पर अनुपालन जाँच और स्कोर तुरंत पुनः चलते हैं, और संशोधन जांच के साथ संग्रहीत होता है (ऑडिट के लिए मूल एआई मान रखा जाता है)।',
  'Sign in as ADMIN / INSPECTOR to correct misread values.':
    'गलत पढ़े गए मान सुधारने के लिए एडमिन / निरीक्षक के रूप में साइन इन करें।',
  CORRECTED: 'संशोधित',
  'Not detected — type a value': 'पता नहीं चला — मान दर्ज करें',
  'Saving…': 'सहेजा जा रहा है…',
  Save: 'सहेजें',
  Cancel: 'रद्द करें',
  'Not detected': 'पता नहीं चला',
  'Original (AI):': 'मूल (एआई):',
  'Correct {field}': '{field} सुधारें',
  'Corrections save automatically to inspection': 'संशोधन अपने आप जांच में सहेजे जाते हैं',
  'open the full report': 'पूरी रिपोर्ट खोलें',
  'for evidence photos, heat-maps and exports.': 'साक्ष्य फ़ोटो, हीट-मैप और निर्यात के लिए।',
  'Rule Violations ({n})': 'नियम उल्लंघन ({n})',
  'Extracted:': 'निष्कर्षित:',
  'Fix:': 'समाधान:',
  'All Rules Passed': 'सभी नियम पारित',
  'No compliance violations detected.': 'कोई अनुपालन उल्लंघन नहीं मिला।',
  'Consistency Checks ({n})': 'संगति जाँच ({n})',
  'Font Measurement': 'फ़ॉन्ट माप',
  Measured: 'मापा गया',
  Required: 'आवश्यक',
  Uncertainty: 'अनिश्चितता',
  'Reading flagged implausible relative to the legal minimum — manual review.':
    'कानूनी न्यूनतम के सापेक्ष माप असंभव प्रतीत हुआ — मैन्युअल समीक्षा आवश्यक।',
  'Calibration:': 'अंशांकन:',
  ' at {n} px/mm': ' {n} px/mm पर',
  'Method:': 'विधि:',
  ' · Measured from photo #{n}': ' · फ़ोटो #{n} से मापा गया',
  'Cannot measure — manual review required.': 'माप संभव नहीं — मैन्युअल समीक्षा आवश्यक।',
  'Reason:': 'कारण:',
  'Evidence Hash': 'साक्ष्य हैश',
  'SHA-256:': 'SHA-256:',
  'ID:': 'ID:',
  'image(s) processed': 'छवि(याँ) संसाधित',
  'Generating PDF...': 'पीडीएफ बन रहा है…',
  'Download PDF Report': 'पीडीएफ रिपोर्ट डाउनलोड करें',
  'Generating Certificate...': 'प्रमाणपत्र बन रहा है…',
  Certificate: 'प्रमाणपत्र',
  'Photo {n}': 'फ़ोटो {n}',
  'PDF report downloaded!': 'पीडीएफ रिपोर्ट डाउनलोड हुई!',
  'Failed to download PDF report': 'पीडीएफ रिपोर्ट डाउनलोड विफल रही',
  'Certificate downloaded!': 'प्रमाणपत्र डाउनलोड हुआ!',
  'Failed to download certificate': 'प्रमाणपत्र डाउनलोड विफल रहा',
  '{field} corrected — score recalculated': '{field} सुधारा गया — स्कोर पुनर्गणना हुई',
  '{field} corrected': '{field} सुधारा गया',
  'Failed to save correction': 'संशोधन सहेजा नहीं जा सका',

  // ---- Inspection report page ----
  'Back to history': 'इतिहास पर वापस जाएँ',
  'Evidence Photos': 'साक्ष्य फ़ोटो',
  'Image unavailable': 'छवि अनुपलब्ध',
  'No evidence images stored.': 'कोई साक्ष्य छवि संग्रहीत नहीं है।',
  'Evidence SHA-256:': 'साक्ष्य SHA-256:',
  'Click a value to correct an AI reading. Corrections are saved to the inspection, rules are re-evaluated, and the original value is kept for audit.':
    'किसी एआई रीडिंग को सुधारने के लिए मान पर क्लिक करें। संशोधन जांच में सहेजे जाते हैं, नियमों का पुनर्मूल्यांकन होता है, और मूल मान ऑडिट के लिए रखा जाता है।',
  'Read-only (ADMIN / INSPECTOR can correct values).': 'केवल-पठनीय (एडमिन / निरीक्षक मान सुधार सकते हैं)।',
  'MANUALLY CORRECTED': 'मैन्युअल रूप से संशोधित',
  'Font Size & Readability': 'फ़ॉन्ट आकार और पठनीयता',
  'Reading flagged implausible relative to the legal minimum — box may have hit the wrong text. Manual review.':
    'कानूनी न्यूनतम के सापेक्ष माप असंभव प्रतीत हुआ — बॉक्स ने गलत टेक्स्ट पकड़ा हो सकता है। मैन्युअल समीक्षा।',
  'VLM text box rejected ({reason}) — value is informational only.':
    'वीएलएम टेक्स्ट बॉक्स अस्वीकृत ({reason}) — मान केवल सूचनात्मक है।',
  'Font-size axis is excluded when no calibration reference (credit card / barcode) is present — the axis is unknown, not a violation.':
    'जब कोई अंशांकन संदर्भ (क्रेडिट कार्ड / बारकोड) मौजूद न हो तो फ़ॉन्ट-आकार अक्ष बाहर रखा जाता है — अक्ष अज्ञात है, उल्लंघन नहीं।',
  'All rules passed': 'सभी नियम पारित',
  'Export JSON': 'JSON निर्यात करें',
  'Export CSV': 'CSV निर्यात करें',
  '{format} exported': '{format} निर्यात हुआ',
  'Export failed': 'निर्यात विफल रहा',
  'Failed to load inspection': 'जांच लोड नहीं हो सकी',

  // ---- Dashboard ----
  'Compliance Dashboard': 'अनुपालन डैशबोर्ड',
  'Live overview of all inspections': 'सभी जांचों का लाइव अवलोकन',
  'Total Inspections': 'कुल जांच',
  'Avg Compliance Score': 'औसत अनुपालन स्कोर',
  'Non-Compliant': 'गैर-अनुपालक',
  'Status Breakdown': 'स्थिति विवरण',
  'No inspections yet.': 'अभी कोई जांच नहीं।',
  'Scans (last 14 days)': 'स्कैन (पिछले 14 दिन)',
  'No data yet.': 'अभी कोई डेटा नहीं।',
  'Violations by Field': 'क्षेत्र के अनुसार उल्लंघन',
  'No violations recorded.': 'कोई उल्लंघन दर्ज नहीं।',
  'Recent Inspections': 'हाल की जांच',
  'Unknown product': 'अज्ञात उत्पाद',
  'Start one now': 'अभी एक शुरू करें',
  'Failed to load dashboard': 'डैशबोर्ड लोड नहीं हो सका',

  // ---- History ----
  'Inspection History': 'जांच इतिहास',
  'Search previously scanned products and reports': 'पहले स्कैन किए गए उत्पादों और रिपोर्टों को खोजें',
  'Search by ID, product name or manufacturer…': 'ID, उत्पाद नाम या निर्माता से खोजें…',
  Searching: 'खोज हो रही है',
  Search: 'खोजें',
  'All statuses': 'सभी स्थितियाँ',
  result: 'परिणाम',
  results: 'परिणाम',
  'No inspections found matching your filters.': 'आपके फ़िल्टर से मेल खाती कोई जांच नहीं मिली।',
  Inspection: 'जांच',
  'Product / Maker': 'उत्पाद / निर्माता',
  Score: 'स्कोर',
  Actions: 'कार्रवाइयाँ',
  View: 'देखें',
  'Search failed': 'खोज विफल रही',
  'CSV downloaded': 'CSV डाउनलोड हुआ',

  // ---- Login ----
  'Legal Metrology Compliance Inspection': 'विधिक मेट्रोलॉजी अनुपालन जांच',
  Username: 'उपयोगकर्ता नाम',
  Password: 'पासवर्ड',
  'Signing in…': 'साइन इन हो रहा है…',
  'Enter username and password': 'उपयोगकर्ता नाम और पासवर्ड दर्ज करें',
  'Welcome, {name}!': 'स्वागत है, {name}!',
  'Login failed': 'लॉगिन विफल रहा',
  'Default demo account: admin / admin@123': 'डिफ़ॉल्ट डेमो खाता: admin / admin@123',
}

const STATUS_HI: Record<string, string> = {
  COMPLIANT: 'अनुपालक',
  REVIEW_REQUIRED: 'समीक्षा आवश्यक',
  POTENTIAL_VIOLATION: 'संभावित उल्लंघन',
}

interface I18nValue {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: string, vars?: Record<string, string | number>) => string
  tStatus: (status: string) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>('en')

  // Hydration-safe: read the saved preference only after mount.
  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved === 'en' || saved === 'hi') setLang(saved)
  }, [])

  useEffect(() => {
    document.documentElement.lang = lang
    window.localStorage.setItem(STORAGE_KEY, lang)
  }, [lang])

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      let s = lang === 'hi' ? HI[key] ?? key : key
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          s = s.split(`{${k}}`).join(String(v))
        }
      }
      return s
    },
    [lang],
  )

  const tStatus = useCallback(
    (status: string) => {
      if (lang === 'hi' && STATUS_HI[status]) return STATUS_HI[status]
      return status.replace(/_/g, ' ')
    },
    [lang],
  )

  const value = useMemo<I18nValue>(() => ({ lang, setLang, t, tStatus }), [lang, t, tStatus])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within I18nProvider')
  return ctx
}
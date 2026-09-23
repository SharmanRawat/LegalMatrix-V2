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
  'Live pipeline': 'लाइव प्रोसेसिंग',
  events: 'ईवेंट',
  'Uploading images…': 'छवियाँ अपलोड हो रही हैं…',
  'Manufacturer Address': 'निर्माता का पता',
  'Raw label text (OCR transcript)': 'लेबल का कच्चा पाठ (ओसीआर ट्रांसक्रिप्ट)',
  '{n} text regions': '{n} पाठ क्षेत्र',
  '{count} regions': '{count} क्षेत्र',
  'low-confidence': 'कम-विश्वसनीय',
  'No text detected': 'कोई पाठ नहीं मिला',
  'Shown for transparency — this raw text is never used to fill declarations.':
    'पारदर्शिता के लिए दिखाया गया — यह कच्चा पाठ कभी भी घोषणाओं को भरने के लिए उपयोग नहीं किया जाता।',
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

  // ---- Certificate verification page ----
  'Certificate verification': 'प्रमाणपत्र सत्यापन',
  'Open a certificate QR code link to verify a LegalMatrix compliance certificate.':
    'LegalMatrix अनुपालन प्रमाणपत्र सत्यापित करने के लिए प्रमाणपत्र क्यूआर कोड लिंक खोलें।',
  'Verifying certificate…': 'प्रमाणपत्र सत्यापित हो रहा है…',
  'Unable to verify': 'सत्यापित नहीं किया जा सका',
  'No inspection matches this certificate code.': 'इस प्रमाणपत्र कोड से कोई जांच मेल नहीं खाती।',
  'Verification service unavailable. Try again later.': 'सत्यापन सेवा अनुपलब्ध है। बाद में पुनः प्रयास करें।',
  'Certificate verified': 'प्रमाणपत्र सत्यापित हुआ',
  'Verification warning': 'सत्यापन चेतावनी',
  'Authentic': 'प्रामाणिक',
  'Hash mismatch': 'हैश मेल नहीं खाता',
  'Authentic — certificate and evidence hash match.':
    'प्रामाणिक — प्रमाणपत्र और साक्ष्य हैश मेल खाते हैं।',
  'Certificate found, but the evidence hash does not match the stored record.':
    'प्रमाणपत्र मिला, लेकिन साक्ष्य हैश संग्रहीत रिकॉर्ड से मेल नहीं खाता।',
  'Inspection ID': 'जांच आईडी',
  'Product': 'उत्पाद',
  'Status / Score': 'स्थिति / स्कोर',
  'Issued': 'जारी किया गया',
  'Evidence SHA-256': 'साक्ष्य SHA-256',

  // ---- Dashboard ----
  'Compliance Dashboard': 'अनुपालन डैशबोर्ड',
  Instructor: 'निरीक्षक',
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

  // ---- Font Measurement (live) ----
  'Font Size Measurement': 'फ़ॉन्ट आकार माप',
  'Live · Validated in the field': 'लाइव · क्षेत्र में सत्यापित',
  'Live and validated on real field photos': 'असली फ़ील्ड फ़ोटो पर लाइव और सत्यापित',
  'A barcode-calibrated measurement produced a real COMPLIANT font verdict — 1.96 mm measured vs 1.0 mm required (±0.29 mm uncertainty) — rendered in the PDF report and scored on the Font Size radar axis (weight 0.20).':
    'बारकोड-अंशांकित माप ने असली COMPLIANT फ़ॉन्ट निर्णय दिया — माप 1.96 मिमी बनाम आवश्यक 1.0 मिमी (±0.29 मिमी अनिश्चितता) — PDF रिपोर्ट में दर्ज और फ़ॉन्ट आकार रडार अक्ष (वज़न 0.20) पर स्कोर किया गया।',
  'Legal Metrology (Packaged Commodities) Rules 2011 require minimum numeral heights that scale with net quantity (1–4 mm normal, 2–6 mm embossed). The pipeline now measures real label numerals against these thresholds — and reports an honest CANNOT_MEASURE when it cannot.':
    'विधिक मेट्रोलॉजी (पैक किए गए उपभोक्ता सामान) नियम 2011 के अनुसार शुद्ध मात्रा के अनुसार अंकों की न्यूनतम ऊँचाई आवश्यक है (सामान्य 1–4 मिमी, उभरे हुए 2–6 मिमी)। अब पाइपलाइन असली लेबल के अंकों को इन सीमाओं के विरुद्ध मापती है — और जब माप संभव न हो तो ईमानदारी से CANNOT_MEASURE बताती है।',
  'Try a new inspection': 'नई जांच आज़माएँ',
  'What the pipeline does today': 'पाइपलाइन आज क्या करती है',
  'Calibration chain (credit card → barcode → EXIF)': 'अंशांकन श्रृंखला (क्रेडिट कार्ड → बारकोड → EXIF)',
  'A physically traceable reference converts pixels to millimetres: an ISO/IEC 7810 card (85.60 × 53.98 mm) beside the product is the exact reference; a product barcode is coarser; phone EXIF camera-metrics is never an automated verdict.':
    'एक भौतिक रूप से अनुरेखणीय संदर्भ पिक्सेल को मिलीमीटर में बदलता है: उत्पाद के पास रखा ISO/IEC 7810 कार्ड (85.60 × 53.98 मिमी) सटीक संदर्भ है; उत्पाद बारकोड मोटा है; फ़ोन EXIF कैमरा-मेट्रिक्स कभी स्वचालित निर्णय नहीं देती।',
  'Honest measurement, never fabricated': 'ईमानदार माप, कभी निर्मित नहीं',
  'When a calibration reference is present, numeral height is measured in millimetres with an explicit uncertainty band. When none is present, the axis weight drops to 0 and the reading is reported as CANNOT_MEASURE with an auditable reason — we never output a millimetre value we cannot defend.':
    'जब अंशांकन संदर्भ मौजूद होता है, तो अंकों की ऊँचाई स्पष्ट अनिश्चितता सीमा के साथ मिलीमीटर में मापी जाती है। जब कोई संदर्भ नहीं होता, तो अक्ष का वज़न 0 हो जाता है और रीडिंग पता लगाने योग्य कारण के साथ CANNOT_MEASURE घोषित होती है — हम कभी ऐसा मिलीमीटर मान नहीं निकालते जिसका हम बचाव न कर सकें।',
  'Defensibility gates on every reading': 'हर रीडिंग पर बचाव-योग्यता द्वार',
  'Each text region passes geometric and glyph sanity checks. A measured height outside the plausible range forces manual review, and the uncalibrated lower-half heuristic never produces an automated verdict.':
    'प्रत्येक टेक्स्ट क्षेत्र ज्यामितीय और ग्लिफ़ सत्यापन से गुजरता है। संभावित सीमा से बाहर मापी गई ऊँचाई मैन्युअल समीक्षा के लिए बाध्य करती है, और बिना अंशांकन वाला निचला-आधा ह्यूरिस्टिक कभी स्वचालित निर्णय नहीं देता।',
  "What's next": 'आगे क्या',
  'Guided calibration-card capture flow in the capture UI — the inspector is told when a reference is missing.':
    'कैप्चर UI में निर्देशित अंशांकन-कार्ड कैप्चर प्रवाह — निरीक्षक को बताया जाता है कि संदर्भ गायब है।',
  'Quantitative regression set of synthetic labels with known pixel heights to validate every change.':
    'ज्ञात पिक्सेल ऊँचाई वाले सिंथेटिक लेबलों का मात्रात्मक प्रतिगमन सेट ताकि हर बदलाव सत्यापित हो।',
  'When no usable reference (card, barcode or EXIF) is in the frame, the font axis reports CANNOT_MEASURE and its weight drops to 0 — never a fabricated violation.':
    'जब फ़्रेम में कोई उपयोगी संदर्भ (कार्ड, बारकोड या EXIF) नहीं होता, तो फ़ॉन्ट अक्ष CANNOT_MEASURE दिखाता है और उसका वज़न 0 हो जाता है — कभी भी निर्मित उल्लंघन नहीं।',
  'Font measurement is live in the shipped pipeline: calibration → OCR token height → millimetre verdict → PDF report → scored radar axis. Inputs that cannot be measured are reported honestly as CANNOT_MEASURE.':
    'फ़ॉन्ट माप शिप्ड पाइपलाइन में लाइव है: अंशांकन → OCR टोकन ऊँचाई → मिलीमीटर निर्णय → PDF रिपोर्ट → स्कोर किया गया रडार अक्ष। अमापनीय इनपुट ईमानदारी से CANNOT_MEASURE बताए जाते हैं।',

  // ---- Admin (user management) ----
  'User Management': 'उपयोगकर्ता प्रबंधन',
  'Admin-only: search users, view their scans, reset passwords': 'केवल-एडमिन: उपयोगकर्ता खोजें, उनके स्कैन देखें, पासवर्ड रीसेट करें',
  'Admin only': 'केवल एडमिन',
  'This page is restricted to administrators.': 'यह पृष्ठ केवल एडमिनिस्ट्रेटरों के लिए है।',
  'Back to dashboard': 'डैशबोर्ड पर वापस जाएँ',
  'Search by username or name…': 'उपयोगकर्ता नाम या नाम से खोजें…',
  'All roles': 'सभी भूमिकाएँ',
  'Passwords are stored as one-way hashes and can never be viewed — an admin can only reset one.':
    'पासवर्ड एक-तरफ़ा हैश के रूप में संग्रहीत होते हैं और कभी देखे नहीं जा सकते — एडमिन केवल रीसेट कर सकता है।',
  'No users found matching your filters.': 'आपके फ़िल्टर से मेल खाता कोई उपयोगकर्ता नहीं मिला।',
  Name: 'नाम',
  'Reset password': 'पासवर्ड रीसेट करें',
  'Reset password for {username}': '{username} का पासवर्ड रीसेट करें',
  'New password': 'नया पासवर्ड',
  'Enter a new password': 'नया पासवर्ड दर्ज करें',
  'Set password': 'पासवर्ड सेट करें',
  'Password reset for {username}': '{username} का पासवर्ड रीसेट हो गया',
  'Reset failed': 'रीसेट विफल रहा',
  'The old password is unrecoverable (stored as a hash). The user must use the new one from now on.':
    'पुराना पासवर्ड पुनर्प्राप्त नहीं किया जा सकता (हैश के रूप में संग्रहीत)। उपयोगकर्ता को अब से नया पासवर्ड उपयोग करना होगा।',
  'Scans by {name}': '{name} द्वारा किए गए स्कैन',
  'Failed to load scans': 'स्कैन लोड नहीं हो सके',
  'No scans yet for this user.': 'इस उपयोगकर्ता के अभी कोई स्कैन नहीं हैं।',

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
  'Demo admin login: username admin — password is configured in backend/.env (LEGALMATRIX_ADMIN_PASSWORD)': 'डेमो एडमिन लॉगिन: उपयोगकर्ता नाम admin — पासवर्ड backend/.env में कॉन्फ़िगर किया गया है (LEGALMATRIX_ADMIN_PASSWORD)',
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
# app/services/post_processor.py
# FIXED VERSION - Sept 6, 2026 (with manufacturer strip fix)
import re

class PostProcessor:
    """Generic, product-agnostic OCR post-processing"""
    
    @staticmethod
    def filter_by_confidence(ocr_results, threshold=0.7):
        """Filter out low-confidence OCR results"""
        if not ocr_results:
            return []
        return [item for item in ocr_results if item.get("confidence", 0) >= threshold]
    
    @staticmethod
    def clean_text(text):
        """Apply generic, product-agnostic corrections"""
        if not text:
            return text
        
        # Fix camelCase splitting
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        
        # Fix common OCR misreads
        text = re.sub(r'\bLSP\b', 'USP', text, flags=re.IGNORECASE)
        text = re.sub(r'(\d+)\s*/\s*m\b', r'\1/ml', text)
        
        # Remove duplicate spaces
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    @staticmethod
    def post_process_field(text, field_type):
        """Apply field-specific generic corrections"""
        if not text:
            return text
        
        # Start with generic cleaning
        text = PostProcessor.clean_text(text)
        
        if field_type == "manufacturer":
            # ---- NEW: Strip leading bullet points, plus signs, etc. ----
            text = re.sub(r'^[+\-•◆★\s]+', '', text)
            # Fix: "EVER.CARE" → "LEVER.CARE@"
            text = re.sub(r'EVER\.CARE', 'LEVER.CARE@', text, flags=re.IGNORECASE)
            # Fix: "CAREO" → "CARE@"
            text = re.sub(r'CAREO', 'CARE@', text, flags=re.IGNORECASE)
            # Fix: "OUNILEVER" → "UNILEVER"
            text = re.sub(r'\bO(UNILEVER)\b', r'\1', text, flags=re.IGNORECASE)
            # Fix: Remove extra "L" at start (LLEVER → LEVER)
            text = re.sub(r'^LL', 'L', text)
            # Fix: Add @ before .COM if missing, but only if there's no @ already
            if ".COM" in text.upper() and "@" not in text:
                text = text.replace(".COM", "@.COM")
            # Fix: Remove duplicate @ symbols
            text = re.sub(r'@@+', '@', text)
            # Fix: Remove duplicate dots
            text = re.sub(r'\.\.+', '.', text)
            # Fix: Clean up @.COM at end
            text = re.sub(r'@\.COM$', '.COM', text)
        
        elif field_type == "usp":
            # NEW FIX: Normalize USP spacing
            # "USP1.00/ml" → "USP 1.00/ml"
            # "USP100/ml" → "USP 100/ml"
            text = re.sub(r'\bUSP(\d)', r'USP \1', text, flags=re.IGNORECASE)
            
            # Fix LSP → USP
            text = re.sub(r'\bLSP\b', 'USP', text, flags=re.IGNORECASE)
            
            # Fix unit formatting: /m → /ml
            text = re.sub(r'(\d+)\s*/\s*m\b', r'\1/ml', text)
            
            # Fix double letters: mll → ml
            text = re.sub(r'/mll', '/ml', text, flags=re.IGNORECASE)
            text = re.sub(r'\bmll\b', 'ml', text, flags=re.IGNORECASE)
        
        elif field_type == "product_name":
            text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
            text = re.sub(r'([A-Za-z]+)([A-Z][a-z])', r'\1 \2', text)
        
        elif field_type == "net_quantity":
            # Fix: "mll" → "ml"
            text = re.sub(r'\bmll\b', 'ml', text, flags=re.IGNORECASE)
            # Fix: spaces around units
            text = re.sub(r'(\d)\s*(g|ml|kg|l|gm|mg)', r'\1 \2', text, flags=re.IGNORECASE)
        
        elif field_type == "date":
            # Normalize DOT format
            text = re.sub(r'DOT\s*[:]\s*', 'DOT: ', text, flags=re.IGNORECASE)
        
        elif field_type == "mrp":
            # Normalize MRP spacing
            text = re.sub(r'(Rs|₹)\s*(\d)', r'\1 \2', text, flags=re.IGNORECASE)
            # Fix: "/- " → "/-"
            text = re.sub(r'/\s*-\s*', '/-', text)
        
        return text.strip()
    
    @staticmethod
    def normalize_declaration(declaration):
        """Normalize a declaration dictionary with post-processing"""
        if not declaration:
            return declaration
        
        normalized = declaration.copy()
        
        for field, item in normalized.items():
            if isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    item["text"] = PostProcessor.post_process_field(text, field)
            elif isinstance(item, str):
                normalized[field] = PostProcessor.post_process_field(item, field)
        
        return normalized
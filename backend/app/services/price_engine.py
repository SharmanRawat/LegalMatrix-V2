import re


class PriceEngine:
    """Unit Sale Price (USP) validation"""
    
    @staticmethod
    def calculate_usp(mrp, net_quantity, unit="g"):
        """
        Calculate expected USP based on MRP and net quantity
        """
        if net_quantity <= 0:
            return None, "Invalid net quantity"
        
        # Convert to standard units
        if unit == "g":
            quantity_in_kg = net_quantity / 1000
            if quantity_in_kg < 1:
                usp_unit = "g"
                usp_value = mrp / net_quantity
            else:
                usp_unit = "kg"
                usp_value = mrp / quantity_in_kg
        elif unit == "kg":
            quantity_in_kg = net_quantity
            if quantity_in_kg < 1:
                usp_unit = "g"
                usp_value = mrp / (net_quantity * 1000)
            else:
                usp_unit = "kg"
                usp_value = mrp / net_quantity
        elif unit == "ml":
            if net_quantity < 1000:
                usp_unit = "ml"
                usp_value = mrp / net_quantity
            else:
                usp_unit = "L"
                usp_value = mrp / (net_quantity / 1000)
        elif unit == "L":
            if net_quantity < 1:
                usp_unit = "ml"
                usp_value = mrp / (net_quantity * 1000)
            else:
                usp_unit = "L"
                usp_value = mrp / net_quantity
        else:
            usp_unit = "unit"
            usp_value = mrp / net_quantity
        
        # Round to 2 decimal places
        rounded_usp = round(usp_value, 2)
        return rounded_usp, usp_unit
    
    @staticmethod
    def validate_usp(declared_usp, expected_usp, tolerance=0.01):
        """
        Validate declared USP against expected USP
        Returns: (is_valid, difference, status)
        """
        if declared_usp is None:
            return False, None, "MISSING_USP"
        
        difference = abs(declared_usp - expected_usp)
        if difference <= tolerance:
            return True, difference, "MATCH"
        else:
            return False, difference, "MISMATCH"
    
    @staticmethod
    def check_usp_exemption(mrp, declared_usp):
        """
        Check if USP declaration is exempt (MRP == USP)
        """
        if mrp is None or declared_usp is None:
            return False
        return abs(mrp - declared_usp) < 0.01

    # Update app/services/price_engine.py

    @staticmethod
    def calculate_usp_from_text(usp_text, mrp):
        """
        Calculate USP from the USP declaration text
        Example: "USP 100/ml" → 100
        """
        if not usp_text:
            return None
        
        # Extract number from USP text
        numbers = re.findall(r'(\d+\.?\d*)', usp_text)
        if numbers:
            return float(numbers[0])
        return None

    @staticmethod
    def extract_unit_from_usp(usp_text):
        """
        Extract unit from USP text
        Example: "USP 100/ml" → "ml"
                "USP ₹10/g" → "g"
        """
        if not usp_text:
            return None
        
        # Look for unit patterns
        unit_patterns = r'(?:/|\s+)(g|ml|kg|l|gm|mg|cm|m)'
        match = re.search(unit_patterns, usp_text, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        
        # If no unit found, check for common patterns
        if '/ml' in usp_text.lower() or ' per ml' in usp_text.lower():
            return 'ml'
        if '/g' in usp_text.lower() or ' per g' in usp_text.lower():
            return 'g'
        if '/kg' in usp_text.lower() or ' per kg' in usp_text.lower():
            return 'kg'
        
        return None

price_engine = PriceEngine()

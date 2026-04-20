#!/bin/bash
# Release Verification Script for AISBF v0.99.37

echo "================================================================================"
echo "                    AISBF v0.99.37 Release Verification"
echo "================================================================================"
echo

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# Function to check status
check() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} $1"
    else
        echo -e "${RED}✗${NC} $1"
        ERRORS=$((ERRORS + 1))
    fi
}

# 1. Check version numbers
echo "1. Checking version numbers..."
VERSION="0.99.37"

grep -q "version=\"$VERSION\"" setup.py
check "setup.py version is $VERSION"

grep -q "version = \"$VERSION\"" pyproject.toml
check "pyproject.toml version is $VERSION"

grep -q "__version__ = \"$VERSION\"" aisbf/__init__.py
check "aisbf/__init__.py version is $VERSION"

echo

# 2. Check Python syntax
echo "2. Checking Python syntax..."
python -m py_compile setup.py 2>/dev/null
check "setup.py compiles"

python -m py_compile aisbf/__init__.py 2>/dev/null
check "aisbf/__init__.py compiles"

python -m py_compile main.py 2>/dev/null
check "main.py compiles"

python -m py_compile aisbf/database.py 2>/dev/null
check "aisbf/database.py compiles"

echo

# 3. Check templates
echo "3. Checking templates..."
TEMPLATE_COUNT=$(ls templates/dashboard/*.html 2>/dev/null | wc -l)
if [ "$TEMPLATE_COUNT" -eq 32 ]; then
    echo -e "${GREEN}✓${NC} Found 32 templates in templates/dashboard/"
else
    echo -e "${RED}✗${NC} Expected 32 templates, found $TEMPLATE_COUNT"
    ERRORS=$((ERRORS + 1))
fi

# Check if paypal_connect.html exists
if [ -f "templates/dashboard/paypal_connect.html" ]; then
    echo -e "${GREEN}✓${NC} paypal_connect.html exists"
else
    echo -e "${RED}✗${NC} paypal_connect.html not found"
    ERRORS=$((ERRORS + 1))
fi

echo

# 4. Check documentation files
echo "4. Checking documentation files..."
for doc in "PAYPAL_SETUP.md" "PAYMENT_INTEGRATION_SUMMARY.md" "DEPLOYMENT_CHECKLIST.md" "QUICK_START_PAYMENT.md"; do
    if [ -f "$doc" ]; then
        echo -e "${GREEN}✓${NC} $doc exists"
    else
        echo -e "${RED}✗${NC} $doc not found"
        ERRORS=$((ERRORS + 1))
    fi
done

echo

# 5. Check requirements.txt
echo "5. Checking requirements.txt..."
if grep -q "paypalrestsdk" requirements.txt; then
    echo -e "${GREEN}✓${NC} paypalrestsdk in requirements.txt"
else
    echo -e "${RED}✗${NC} paypalrestsdk not in requirements.txt"
    ERRORS=$((ERRORS + 1))
fi

echo

# 6. Check CHANGELOG.md
echo "6. Checking CHANGELOG.md..."
if grep -q "0.99.26" CHANGELOG.md; then
    echo -e "${GREEN}✓${NC} Version 0.99.26 in CHANGELOG.md"
else
    echo -e "${RED}✗${NC} Version 0.99.26 not in CHANGELOG.md"
    ERRORS=$((ERRORS + 1))
fi

echo

# 7. Check imports
echo "7. Checking Python imports..."
python -c "import aisbf; print('✓ aisbf imports successfully')" 2>/dev/null
check "aisbf module imports"

python -c "from main import app; print('✓ main.py imports successfully')" 2>/dev/null
check "main.py imports"

echo

# 8. Check git status
echo "8. Checking git status..."
if git diff --cached --quiet; then
    echo -e "${YELLOW}⚠${NC}  No changes staged for commit"
else
    STAGED=$(git diff --cached --name-only | wc -l)
    echo -e "${GREEN}✓${NC} $STAGED files staged for commit"
fi

echo

# 9. Check setup.py templates
echo "9. Checking setup.py template list..."
SETUP_TEMPLATES=$(grep -c "templates/dashboard/" setup.py)
if [ "$SETUP_TEMPLATES" -eq 32 ]; then
    echo -e "${GREEN}✓${NC} All 32 templates listed in setup.py"
else
    echo -e "${RED}✗${NC} Expected 32 templates in setup.py, found $SETUP_TEMPLATES"
    ERRORS=$((ERRORS + 1))
fi

echo

# Summary
echo "================================================================================"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ ALL CHECKS PASSED${NC}"
    echo
    echo "Release v0.99.26 is ready for:"
    echo "  1. Git commit and tag"
    echo "  2. PyPI build (./build.sh)"
    echo "  3. PyPI upload (twine upload dist/*)"
    echo "  4. Production deployment"
else
    echo -e "${RED}❌ $ERRORS CHECK(S) FAILED${NC}"
    echo
    echo "Please fix the issues above before releasing."
fi
echo "================================================================================"

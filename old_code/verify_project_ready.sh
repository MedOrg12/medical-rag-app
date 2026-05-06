#!/bin/bash
# Verify all fixes are in place before zipping

echo "🔍 Verifying Medical Research RAG Project..."
echo ""

ERRORS=0

# Check critical files exist
echo "📁 Checking critical files..."
FILES=(
    "Dockerfile"
    "docker-entrypoint.sh"
    "docker-compose.yml"
    "api/ingest.py"
    "static/index.html"
    "app_icon.ico"
    "installer.iss"
    "requirements.txt"
    ".env"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file"
    else
        echo "  ❌ $file - MISSING!"
        ((ERRORS++))
    fi
done

echo ""
echo "🔧 Verifying fixes..."

# Check Docker entrypoint
if grep -q "chmod 777 /app/pdfs" Dockerfile; then
    echo "  ✅ Dockerfile has 777 permissions"
else
    echo "  ❌ Dockerfile missing 777 permissions"
    ((ERRORS++))
fi

if grep -q "ENTRYPOINT.*docker-entrypoint.sh" Dockerfile; then
    echo "  ✅ Dockerfile has ENTRYPOINT directive"
else
    echo "  ❌ Dockerfile missing ENTRYPOINT"
    ((ERRORS++))
fi

# Check entrypoint script
if grep -q "pdfs folder write test passed" docker-entrypoint.sh; then
    echo "  ✅ Entrypoint has permission verification"
else
    echo "  ❌ Entrypoint missing verification"
    ((ERRORS++))
fi

# Check API fix
if grep -q "async def upload_pdfs(files: list\[UploadFile\]" api/ingest.py; then
    echo "  ✅ Upload endpoint simplified (no Request param)"
else
    echo "  ❌ Upload endpoint not fixed"
    ((ERRORS++))
fi

# Check GUI fixes
if grep -q "return_context: true" static/index.html; then
    echo "  ✅ Query context enabled"
else
    echo "  ❌ Query context not enabled"
    ((ERRORS++))
fi

if grep -q "const loadingElement = document.getElementById(loadingId);" static/index.html; then
    echo "  ✅ Query spinner null check added"
else
    echo "  ❌ Query spinner not fixed"
    ((ERRORS++))
fi

if grep -q "localStorage.getItem('autoIngestBannerDismissed')" static/index.html; then
    echo "  ✅ Banner persistence added"
else
    echo "  ❌ Banner persistence not added"
    ((ERRORS++))
fi

# Check icon
if grep -q "SetupIconFile=app_icon.ico" installer.iss; then
    echo "  ✅ Installer icon configured"
else
    echo "  ❌ Installer icon not configured"
    ((ERRORS++))
fi

echo ""
if [ $ERRORS -eq 0 ]; then
    echo "✅ All checks passed! Project is ready to zip and transfer."
    echo ""
    echo "📦 Next steps:"
    echo "   1. Zip the entire project folder"
    echo "   2. Transfer to Windows"
    echo "   3. Extract to C:\\Program Files\\MedicalResearchRAG"
    echo "   4. Run: docker compose build --no-cache"
    echo "   5. Run: docker compose up -d"
    echo "   6. Test upload!"
else
    echo "❌ Found $ERRORS error(s). Please fix before transferring."
    exit 1
fi

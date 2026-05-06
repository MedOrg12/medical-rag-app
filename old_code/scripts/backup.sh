#!/bin/bash
# Backup script for Medical Research RAG Pipeline
# Creates timestamped backups of vector database, data cache, and PDFs

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="medical-rag-backup-${TIMESTAMP}"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Medical Research RAG - Backup Script          ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════╝${NC}"
echo ""

# Create backup directory
mkdir -p "${BACKUP_PATH}"
echo -e "${GREEN}✓${NC} Created backup directory: ${BACKUP_PATH}"

# Check if running in Docker
if [ -f /.dockerenv ]; then
    echo -e "${YELLOW}⚠${NC} Running inside Docker container"
    VECTOR_DB_PATH="/app/vector_db"
    DATA_PATH="/app/data"
    PDF_PATH="/app/pdfs"
    LOGS_PATH="/app/logs"
else
    echo -e "${BLUE}ℹ${NC} Running on host system"
    VECTOR_DB_PATH="${PROJECT_DIR}/vector_db"
    DATA_PATH="${PROJECT_DIR}/data"
    PDF_PATH="${PROJECT_DIR}/pdfs"
    LOGS_PATH="${PROJECT_DIR}/logs"
fi

# Function to backup directory
backup_directory() {
    local source="$1"
    local name="$2"

    if [ -d "$source" ] && [ "$(ls -A $source 2>/dev/null)" ]; then
        echo -e "${BLUE}→${NC} Backing up ${name}..."
        tar -czf "${BACKUP_PATH}/${name}.tar.gz" -C "$(dirname $source)" "$(basename $source)"
        local size=$(du -sh "${BACKUP_PATH}/${name}.tar.gz" | cut -f1)
        echo -e "${GREEN}✓${NC} ${name} backed up (${size})"
    else
        echo -e "${YELLOW}⚠${NC} ${name} is empty or doesn't exist, skipping"
    fi
}

# Backup vector database (most important!)
backup_directory "$VECTOR_DB_PATH" "vector_db"

# Backup data cache
backup_directory "$DATA_PATH" "data"

# Backup PDFs
backup_directory "$PDF_PATH" "pdfs"

# Backup logs from Docker volume (optional)
echo -e "${BLUE}→${NC} Backing up logs from Docker volume..."
docker run --rm -v logs_data:/logs -v "${BACKUP_PATH}":/backup alpine tar -czf /backup/logs.tar.gz -C / logs 2>/dev/null || echo -e "${YELLOW}⚠${NC} No logs volume found, skipping"

# Backup configuration files
echo -e "${BLUE}→${NC} Backing up configuration files..."
cp "${PROJECT_DIR}/.env" "${BACKUP_PATH}/.env" 2>/dev/null || echo -e "${YELLOW}⚠${NC} No .env file found"
cp "${PROJECT_DIR}/docker-compose.yml" "${BACKUP_PATH}/docker-compose.yml"
cp "${PROJECT_DIR}/requirements.txt" "${BACKUP_PATH}/requirements.txt"
echo -e "${GREEN}✓${NC} Configuration files backed up"

# Create metadata file
cat > "${BACKUP_PATH}/backup-metadata.txt" <<EOF
Medical Research RAG - Backup Metadata
======================================
Backup Date: $(date)
Hostname: $(hostname)
Backup Path: ${BACKUP_PATH}
Project Directory: ${PROJECT_DIR}

Contents:
- Vector Database: $([ -f "${BACKUP_PATH}/vector_db.tar.gz" ] && echo "Yes" || echo "No")
- Data Cache: $([ -f "${BACKUP_PATH}/data.tar.gz" ] && echo "Yes" || echo "No")
- PDFs: $([ -f "${BACKUP_PATH}/pdfs.tar.gz" ] && echo "Yes" || echo "No")
- Logs: $([ -f "${BACKUP_PATH}/logs.tar.gz" ] && echo "Yes" || echo "No")
- Configuration: $([ -f "${BACKUP_PATH}/docker-compose.yml" ] && echo "Yes" || echo "No")

Backup Size: $(du -sh "${BACKUP_PATH}" | cut -f1)
EOF

echo -e "${GREEN}✓${NC} Metadata file created"

# Calculate total backup size
TOTAL_SIZE=$(du -sh "${BACKUP_PATH}" | cut -f1)

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Backup completed successfully!                 ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Backup Location:${NC} ${BACKUP_PATH}"
echo -e "${BLUE}Total Size:${NC} ${TOTAL_SIZE}"
echo ""
echo -e "${YELLOW}To restore this backup, run:${NC}"
echo -e "  ./scripts/restore.sh ${BACKUP_NAME}"
echo ""

# Create a "latest" symlink
cd "${BACKUP_DIR}"
rm -f latest
ln -s "${BACKUP_NAME}" latest
echo -e "${GREEN}✓${NC} Created 'latest' symlink"

exit 0

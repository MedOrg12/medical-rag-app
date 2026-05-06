#!/bin/bash
# Restore script for Medical Research RAG Pipeline
# Restores vector database, data cache, and PDFs from backup

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-./backups}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Medical Research RAG - Restore Script         ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════╝${NC}"
echo ""

# Check if backup name provided
if [ -z "$1" ]; then
    echo -e "${YELLOW}Available backups:${NC}"
    ls -1 "${BACKUP_DIR}" | grep "medical-rag-backup-" || echo "No backups found"
    echo ""
    echo -e "${RED}Usage:${NC} $0 <backup-name>"
    echo -e "${BLUE}Example:${NC} $0 medical-rag-backup-20260311_143000"
    echo -e "${BLUE}Or use:${NC} $0 latest"
    exit 1
fi

BACKUP_NAME="$1"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

# Check if backup exists
if [ ! -d "$BACKUP_PATH" ]; then
    echo -e "${RED}✗${NC} Backup not found: ${BACKUP_PATH}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Found backup: ${BACKUP_PATH}"

# Display backup metadata
if [ -f "${BACKUP_PATH}/backup-metadata.txt" ]; then
    echo ""
    echo -e "${BLUE}Backup Information:${NC}"
    cat "${BACKUP_PATH}/backup-metadata.txt"
    echo ""
fi

# Confirm restoration
echo -e "${YELLOW}⚠ WARNING:${NC} This will replace existing data!"
read -p "Continue with restoration? (yes/no): " -r
echo
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Restoration cancelled"
    exit 0
fi

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

# Function to restore directory
restore_directory() {
    local archive="${BACKUP_PATH}/$1.tar.gz"
    local target_parent="$(dirname $2)"
    local target_name="$(basename $2)"
    local display_name="$1"

    if [ -f "$archive" ]; then
        echo -e "${BLUE}→${NC} Restoring ${display_name}..."

        # Backup existing directory if it exists
        if [ -d "$2" ]; then
            echo -e "${YELLOW}  ↳${NC} Backing up existing ${display_name} to ${2}.old"
            rm -rf "${2}.old"
            mv "$2" "${2}.old"
        fi

        # Extract archive
        mkdir -p "$target_parent"
        tar -xzf "$archive" -C "$target_parent"

        echo -e "${GREEN}✓${NC} ${display_name} restored"
    else
        echo -e "${YELLOW}⚠${NC} No ${display_name} backup found, skipping"
    fi
}

# Stop running containers if Docker Compose is used
if command -v docker-compose &> /dev/null || command -v docker &> /dev/null; then
    echo -e "${BLUE}→${NC} Stopping running containers..."
    docker compose down 2>/dev/null || docker-compose down 2>/dev/null || echo -e "${YELLOW}⚠${NC} No containers to stop"
fi

# Restore vector database (most important!)
restore_directory "vector_db" "$VECTOR_DB_PATH"

# Restore data cache
restore_directory "data" "$DATA_PATH"

# Restore PDFs
restore_directory "pdfs" "$PDF_PATH"

# Restore logs (optional)
if [ -f "${BACKUP_PATH}/logs.tar.gz" ]; then
    restore_directory "logs" "$LOGS_PATH"
fi

# Restore configuration files
echo -e "${BLUE}→${NC} Restoring configuration files..."
if [ -f "${BACKUP_PATH}/.env" ]; then
    cp "${BACKUP_PATH}/.env" "${PROJECT_DIR}/.env"
    echo -e "${GREEN}✓${NC} .env restored"
fi
if [ -f "${BACKUP_PATH}/docker-compose.yml" ]; then
    # Backup existing docker-compose.yml
    if [ -f "${PROJECT_DIR}/docker-compose.yml" ]; then
        cp "${PROJECT_DIR}/docker-compose.yml" "${PROJECT_DIR}/docker-compose.yml.backup"
    fi
    echo -e "${YELLOW}  ↳${NC} docker-compose.yml backed up (you may want to review changes)"
fi

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Restoration completed successfully!            ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Review configuration files if needed"
echo "  2. Start the application:"
echo "     ${GREEN}docker compose up -d${NC}"
echo ""
echo -e "${YELLOW}Note:${NC} Old data backed up to *.old directories"
echo ""

exit 0

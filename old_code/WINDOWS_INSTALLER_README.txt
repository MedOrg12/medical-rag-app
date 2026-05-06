╔══════════════════════════════════════════════════════════════════════════════╗
║           MEDICAL RESEARCH RAG PIPELINE - WINDOWS INSTALLER                  ║
║                        Quick Start Guide                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

Thank you for installing Medical Research RAG Pipeline!

This application uses AI to analyze medical research papers locally on your
computer - no cloud services, completely private.

┌──────────────────────────────────────────────────────────────────────────────┐
│ PREREQUISITE: DOCKER DESKTOP                                                │
└──────────────────────────────────────────────────────────────────────────────┘

This application requires Docker Desktop to run.

📥 Download Docker Desktop:
   https://www.docker.com/products/docker-desktop/

Installation Steps:
1. Download Docker Desktop installer
2. Run the installer (requires admin rights)
3. Restart your computer when prompted
4. Launch Docker Desktop from Start Menu
5. Wait for "Docker Desktop is running" (green icon in system tray)

┌──────────────────────────────────────────────────────────────────────────────┐
│ GETTING STARTED                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

After installing Docker Desktop:

OPTION 1: Use Desktop Shortcut
  • Double-click "Medical Research RAG" icon on your desktop
  • Wait for startup (10-20 seconds)
  • Browser opens automatically to http://localhost:8000

OPTION 2: Use Start Menu
  • Press Windows key
  • Type "Medical Research RAG"
  • Click "Start Medical RAG"

┌──────────────────────────────────────────────────────────────────────────────┐
│ FIRST TIME SETUP (ONE-TIME, ~30 MINUTES)                                    │
└──────────────────────────────────────────────────────────────────────────────┘

The first time you run the application, you need to download AI models (~5GB).

RECOMMENDED: Complete setup automatically after installation
  • Check "Complete setup now" option at the end of installation
  • This will download models, build containers, start the app, and ingest sample PDFs
  • Takes 15-40 minutes but everything will be ready when done!
  • Browser opens automatically and you can watch the progress

OR run setup manually from Start Menu:
  • Medical Research RAG → Complete Setup (First Time)

OR download models separately:
  • Medical Research RAG → Download AI Models

This downloads:
  • Embedding model (274MB) - 2-5 minutes
  • LLM model (4.7GB) - 10-30 minutes

This only needs to be done ONCE. Models are saved permanently.

┌──────────────────────────────────────────────────────────────────────────────┐
│ USING THE APPLICATION                                                        │
└──────────────────────────────────────────────────────────────────────────────┘

The web interface has 3 tabs:

📄 INGEST TAB
   • Upload PDF files (drag and drop)
   • Automatic processing of PDFs in pdfs/ folder
   • View ingestion progress in real-time
   • 20 sample medical research papers included!

💬 QUERY TAB
   • Ask questions about your documents
   • Get AI-powered answers with citations
   • View source references and page numbers
   • Adjust settings (model, temperature, etc.)

📊 METRICS TAB
   • View database statistics
   • Check system health
   • Monitor cache performance
   • See processing history

┌──────────────────────────────────────────────────────────────────────────────┐
│ AVAILABLE SHORTCUTS (START MENU)                                            │
└──────────────────────────────────────────────────────────────────────────────┘

All shortcuts are in: Start Menu → Medical Research RAG Pipeline

• Complete Setup (First Time) - One-time setup: builds containers & downloads models
• Start Medical RAG           - Starts the application
• Stop Medical RAG            - Stops the application (preserves data)
• Check Status                - Shows system status and health
• Download AI Models          - Downloads required AI models (if not done during setup)
• Open Web Interface          - Opens http://localhost:8000 in browser

┌──────────────────────────────────────────────────────────────────────────────┐
│ STOPPING THE APPLICATION                                                     │
└──────────────────────────────────────────────────────────────────────────────┘

To stop the application:

• Start Menu → Medical Research RAG → Stop Medical RAG
  OR
• Run STOP_APP.bat from the installation folder

Your data is automatically saved and will be available next time you start.

┌──────────────────────────────────────────────────────────────────────────────┐
│ ADDING YOUR OWN PDFs                                                         │
└──────────────────────────────────────────────────────────────────────────────┘

OPTION 1: Via Web Interface
  • Open http://localhost:8000
  • Go to Ingest tab
  • Drag and drop PDF files
  • Click "Start Ingestion"

OPTION 2: Via pdfs/ Folder
  • Copy PDF files to: [Installation Folder]\pdfs\
  • Restart the application
  • PDFs are automatically ingested on startup

┌──────────────────────────────────────────────────────────────────────────────┐
│ INSTALLATION LOCATION                                                        │
└──────────────────────────────────────────────────────────────────────────────┘

Default: C:\Program Files\MedicalResearchRAG\

Files included:
  • Docker configuration (docker-compose.yml, Dockerfile)
  • Application code (src/, api/, static/)
  • Batch scripts (START_APP.bat, STOP_APP.bat, etc.)
  • Documentation (README.md, DOCKER_SETUP.md)
  • Sample PDFs (pdfs/ folder - 20 medical research papers)

Data storage (created on first run):
  • vector_db/  - Vector database (contains all embeddings)
  • data/       - Cache and progress tracking
  • logs/       - Application logs

┌──────────────────────────────────────────────────────────────────────────────┐
│ SYSTEM REQUIREMENTS                                                          │
└──────────────────────────────────────────────────────────────────────────────┘

Minimum:
  • Windows 10 64-bit (Build 19041+) or Windows 11
  • 8GB RAM
  • 20GB free disk space
  • Intel or AMD 64-bit processor

Recommended:
  • Windows 11
  • 16GB RAM
  • 30GB free disk space (SSD preferred)
  • Multi-core processor (4+ cores)
  • Good internet connection (for initial model download)

┌──────────────────────────────────────────────────────────────────────────────┐
│ TROUBLESHOOTING                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

❌ "Docker Desktop is not running"
   → Start Docker Desktop from Start Menu
   → Wait for green icon in system tray

❌ "Port 8000 already in use"
   → Close other applications using port 8000
   → Or edit docker-compose.yml to use different port

❌ "Cannot connect to Ollama"
   → Run "Download AI Models" from Start Menu
   → Wait for download to complete

❌ Application won't start
   → Run "Check Status" from Start Menu
   → Check Docker Desktop is running
   → Restart Docker Desktop if needed

❌ Slow performance
   → Docker Desktop → Settings → Resources
   → Increase CPUs to 4+ and RAM to 8GB+
   → Click Apply & Restart

For detailed troubleshooting, see DOCKER_SETUP.md in the installation folder.

┌──────────────────────────────────────────────────────────────────────────────┐
│ UNINSTALLING                                                                 │
└──────────────────────────────────────────────────────────────────────────────┘

To completely remove the application:

1. Stop the application first:
   • Start Menu → Medical Research RAG → Stop Medical RAG

2. Uninstall via Windows:
   • Settings → Apps → Medical Research RAG Pipeline → Uninstall

3. (Optional) Remove Docker data:
   Open Command Prompt and run:
   docker volume rm healthcareproject_ollama_data
   docker volume rm healthcareproject_vector_db
   docker volume rm healthcareproject_data_cache

┌──────────────────────────────────────────────────────────────────────────────┐
│ MORE INFORMATION                                                             │
└──────────────────────────────────────────────────────────────────────────────┘

Documentation files in installation folder:
  • README.md              - Full project documentation
  • DOCKER_SETUP.md        - Detailed Docker setup and troubleshooting
  • QUICK_START_DOCKER.txt - Quick reference commands
  • QUICK_START_WEB_UI.txt - Web interface guide

GitHub Repository:
  https://github.com/MoCode98/medical-research-rag

┌──────────────────────────────────────────────────────────────────────────────┐
│ PRIVACY & DATA                                                               │
└──────────────────────────────────────────────────────────────────────────────┘

✅ 100% Local Processing - All AI runs on your computer
✅ No Cloud Services - No data sent to external servers
✅ No API Keys Required - Completely self-contained
✅ Your Data Stays Private - PDFs never leave your machine

┌──────────────────────────────────────────────────────────────────────────────┐
│ NEED HELP?                                                                   │
└──────────────────────────────────────────────────────────────────────────────┘

1. Check DOCKER_SETUP.md for detailed troubleshooting
2. Run "Check Status" to diagnose issues
3. Visit: https://github.com/MoCode98/medical-research-rag/issues

╔══════════════════════════════════════════════════════════════════════════════╗
║                   Ready to start? Run START_APP.bat! 🚀                      ║
╚══════════════════════════════════════════════════════════════════════════════╝

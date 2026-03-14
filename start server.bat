@echo off

cd /d F:\doc-mapa-v2

call .venv\Scripts\activate

streamlit run app.py ^
--server.address 0.0.0.0 ^
--server.port 2645 ^
--server.headless true ^
--browser.gatherUsageStats false ^
--server.fileWatcherType none
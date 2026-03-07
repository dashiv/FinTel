@ECHO OFF
TITLE FinTel Dashboard
cd "C:\Users\iamsh\OneDrive\Desktop\AI Project\fintel"
call venv\Scripts\activate.bat
streamlit run dashboard/app.py --server.address 0.0.0.0 --server.port 8501

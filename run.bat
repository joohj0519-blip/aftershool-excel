@echo off
echo 필수 패키지를 확인하고 설치하는 중입니다... (최초 1회만 시간이 소요될 수 있습니다)
pip install -r requirements.txt
echo.
echo 방과후학교 대시보드를 실행 중입니다... 잠시만 기다려주세요!
streamlit run app.py
pause

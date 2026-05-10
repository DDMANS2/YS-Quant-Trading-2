# 📈 이평선 돌파 스크리너 - 설치 및 실행 가이드

코딩 거의 안 해보신 분도 따라할 수 있게 단계별로 적었습니다.

---

## 1단계: 파이썬 설치 (5분)

### Windows
1. https://www.python.org/downloads/ 접속
2. **"Download Python 3.12.x"** 노란 버튼 클릭
3. 다운로드된 파일 실행
4. **⚠️ 매우 중요**: 설치 첫 화면에서 **"Add Python to PATH"** 체크박스 반드시 체크!
5. "Install Now" 클릭

### Mac
1. https://www.python.org/downloads/ 접속
2. macOS용 다운로드 후 설치

### 설치 확인
- Windows: `Win + R` → `cmd` 입력 → 검은 창에서 `python --version` 입력
- Mac: 터미널 열고 `python3 --version` 입력
- `Python 3.12.x` 같은 게 나오면 성공

---

## 2단계: 프로젝트 폴더 만들기

1. 바탕화면에 `stock-screener` 폴더 생성
2. 첨부드린 두 파일을 그 폴더에 넣기:
   - `app.py`
   - `requirements.txt`

---

## 3단계: 라이브러리 설치 (3분)

### Windows
1. `stock-screener` 폴더에서 빈 공간에 **Shift + 우클릭** → "여기에 PowerShell 창 열기" 또는 "여기서 명령 프롬프트 열기"
2. 검은 창에 아래 명령어 입력:
   ```
   pip install -r requirements.txt
   ```
3. 5분 정도 설치 진행됨

### Mac
1. `stock-screener` 폴더에서 우클릭 → "폴더에서 새로운 터미널 열기"
2. 아래 명령어 입력:
   ```
   pip3 install -r requirements.txt
   ```

---

## 4단계: 실행!

같은 검은 창에서:
```
streamlit run app.py
```

자동으로 브라우저가 열리며 `http://localhost:8501` 주소로 접속됩니다.

🎉 **이제 본인 PC에서 사이트로 작동합니다!**

종료하려면 검은 창에서 `Ctrl + C` 누르면 됩니다.

---

## 5단계: 인터넷에 무료 배포 (선택)

본인 PC가 아닌 어디서든 접속하고 싶다면:

### Streamlit Community Cloud (완전 무료)

1. **GitHub 가입**: https://github.com → Sign up
2. **새 저장소 만들기**: 
   - "+" 버튼 → "New repository"
   - 이름: `stock-screener`
   - Public 선택 → Create
3. **파일 업로드**: 
   - "uploading an existing file" 클릭
   - `app.py`, `requirements.txt` 드래그
   - "Commit changes"
4. **Streamlit Cloud 연결**:
   - https://share.streamlit.io/ 접속
   - GitHub 계정으로 로그인
   - "New app" → 방금 만든 저장소 선택 → `app.py` 선택
   - "Deploy" 클릭
5. 5분 후 `https://your-name-stock-screener.streamlit.app` 같은 주소 생성됨

이 주소를 폰 북마크에 넣으면 모바일에서도 그대로 사용 가능!

---

## 자주 묻는 질문

### Q. "pip이 인식되지 않습니다" 오류
A. 1단계에서 "Add Python to PATH" 체크 안 한 것. 파이썬 재설치하세요.

### Q. 스크리닝이 너무 느려요
A. 전체 2,600여 종목을 모두 스캔해서 5~10분 걸립니다. 한 번 실행하면 1시간 동안 캐시되니 조건만 바꿔서 다시 돌리면 빨라집니다.

### Q. 에러가 나요
A. 검은 창에 뜨는 빨간 글씨를 캡처해서 저(Claude)에게 보여주세요.

### Q. 결과가 너무 많아요/적어요
A. 사이드바 조건 조정:
- 너무 많음 → 거래량 최소값 ↑, 돌파 시점 ↓
- 너무 적음 → 돌파 시점 ↑, 거래량 최소값 ↓

---

## 향후 추가 가능한 기능

원하시면 아래 기능도 추가해드릴 수 있어요:
- 차트 시각화 (실제 캔들차트 표시)
- 거래량 급증 종목 필터
- 외국인/기관 매수 종목 필터
- RSI, MACD 등 다른 지표 추가
- 관심종목 저장 기능
- 매일 자동으로 결과 이메일 발송

필요한 기능 말씀해주시면 코드 업데이트해드릴게요!

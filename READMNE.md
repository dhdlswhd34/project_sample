# README

## 📘 프로젝트 샘플 코드 모음
이 저장소는 실제 프로젝트에서 구현했던 주요 기능들을 정리한 **샘플 코드 모음집**입니다.  
각 코드들은 프로젝트에서 활용했던 구현 방식을 보여주기 위한 예시입니다.  

---

## 1. chunked_upload
- **업로드 처리** 샘플 코드  
- 업로드 시 **청크 단위 저장**, **중단 지점부터 이어서 업로드 가능**  
- 업로드 진행 상태를 **Redis 캐싱**하여 실시간 상태 조회 가능  

---

## 2. GPT_Stream
- **OpenAI GPT API 연동** 샘플 코드  
- Chat / Complete API 제공 (대화형 / 문서 작성)  
- **스트리밍 응답(SSE)** 지원으로 실시간 대화 경험 제공  

---

## 3. Re_Ranking
- **BM25 + BERT 기반 Re-Ranking 모델** 샘플 코드
- BM25로 1차 검색 후 상위 Passage를 BERT로 Re-Ranking
- `CEDR`, `Passage Re-ranking with BERT` 논문 아이디어 활용
- 한국어 환경에 맞게 **다국어 모델(Multi-lingual BERT)** 적용 


---


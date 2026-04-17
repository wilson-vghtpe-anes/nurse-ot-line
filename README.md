# Nurse OT LINE Bot

這個專案是一個用 `FastAPI` 實作的 LINE webhook 服務，提供：

- `綁定 姓名`
- `加班 YYYY-MM-DD 班別 時數`
- `加班 YYYY-MM-DD 其他 班別名稱 時數`

## 本機執行

1. 安裝套件
```bash
pip install -r requirements.txt
```

2. 設定 `.env`
```env
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_key
```

3. 啟動服務
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 雲端部署

這個專案已經加上 `Dockerfile`，可以部署到支援 Docker 的平台，例如：

- Render
- Railway
- Fly.io
- Google Cloud Run

### Render 最短路徑

1. 把這個資料夾放到 GitHub repo。
2. 到 Render 建立新的 `Web Service`，來源選 GitHub repo。
3. 選擇這個 repo 後，Render 會讀到 `render.yaml`。
4. 在 Render 設定環境變數：
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
5. 確認服務使用 Docker 部署，並讓 Render 對外提供 HTTP 服務。
6. 部署完成後，確認：
   - `/health` 可回應
   - 例如 `https://your-service.onrender.com/health`
7. 到 LINE Developers，把 webhook URL 改成：
   - `https://your-service.onrender.com/webhook`

Render 官方文件指出：
- Docker 型 web service 可以直接用 repo 裡的 `Dockerfile`
- `healthCheckPath` 可在 `render.yaml` 指定
- Web service 必須綁定 `0.0.0.0`，並監聽 Render 提供的埠；此專案已改成讀取 `PORT`，預設 `10000`

## 健康檢查

- `GET /`
- `GET /health`

`/health` 會顯示目前是否缺少必要環境變數，方便部署後驗證。

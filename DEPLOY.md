# 缺陷图谱识别系统 — 部署说明 (端口 5000)

## 1. 系统依赖 (apt)
sudo apt update
sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim

## 2. Python 环境 (建议 conda 或 venv, Python 3.10+)
python -m venv venv && source venv/bin/activate
# 或 conda create -n myenv python=3.11 && conda activate myenv

pip install -r requirements.txt

## 3. 启动 Web 服务 (端口 5000)
python cli.py serve --host 0.0.0.0 --port 5000

浏览器访问: http://<服务器IP>:5000/

## 4. 后台常驻 (systemd, 推荐)
sudo systemd-run --unit=defect-web-5000 --working-directory=$(pwd)   $(which python) cli.py serve --host 0.0.0.0 --port 5000

# 管理:
sudo systemctl status defect-web-5000
sudo systemctl restart defect-web-5000
journalctl -u defect-web-5000 -f

## 5. 验证 OCR 可用
python -c "import pytesseract, cv2; print('tesseract:', pytesseract.get_tesseract_version())"
tesseract --list-langs   # 应含 chi_sim, eng

## 备注
- 登录账号在 .auth 文件 (格式 admin:密码), 首次可自行修改或删除该文件重新生成
- 输入: 上传 .xls/.xlsx 缺陷图谱表; 输出: output/<任务id>/
- 识别引擎: Tesseract + OpenCV 密度法小黑卡检测 (无 easyocr/GPU 依赖)

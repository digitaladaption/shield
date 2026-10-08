FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# regenerate the demo match and bundle at build time so the image is self-contained
RUN python -m shield.generator.generate --seed 7 --out data/match_7 \
 && python -m shield.generator.generate --seed 7 --no-shield --out data/match_7_control \
 && python -m shield.engine.build_bundle --match data/match_7 --control data/match_7_control
EXPOSE 8080
CMD ["uvicorn", "shield.server:app", "--host", "0.0.0.0", "--port", "8080"]

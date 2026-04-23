FROM python:3.12-alpine

WORKDIR /app

COPY app.py /app/app.py

ENV PORT=8080
ENV OATHKEEPER_PROXY_HOST=oathkeeper
ENV OATHKEEPER_PROXY_PORT=4455

EXPOSE 8080

CMD ["python", "/app/app.py"]

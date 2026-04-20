FROM node:20-alpine

WORKDIR /app

# Копируем npm конфигурацию для увеличения таймаутов
COPY .npmrc* ./
COPY package.json package-lock.json* ./

# Устанавливаем зависимости с повторными попытками при ошибке
RUN if [ -f package-lock.json ]; then \
      npm ci --prefer-offline --no-audit || \
      npm ci --prefer-offline --no-audit || \
      npm ci --no-audit; \
    else \
      npm install --prefer-offline --no-audit; \
    fi

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]

FROM node:22-alpine
COPY app/ /usr/src/app/
WORKDIR /usr/src/app
RUN npm install
RUN apk update; apt upgrade; apk COPY git
CMD [ "npm", "start" ]
EXPOSE 80

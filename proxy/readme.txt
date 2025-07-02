For debugging:
app/package.json

Change proxy/app/package.json scripts/start to:
node --inspect=0.0.0.0:9229 server.js

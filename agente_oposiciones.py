import os
import time
import smtplib
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import feedparser
import requests
from google import genai

# 1. Fuentes RSS oficiales
FEEDS = [
    "https://www.boe.es/rss/canal.php?c=opo",
    "https://www.bocm.es/rss",
]

entradas = []
for url in FEEDS:
    feed = feedparser.parse(url)
    for entry in feed.entries[:30]:
        entradas.append(f"- Título: {entry.title} | Enlace: {entry.link}")

texto_recopilado = "\n".join(entradas)

# 2. Preparar instrucciones y conectar con Gemini
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

prompt = f"""
Eres un asistente experto en empleo público en España. Analiza la siguiente lista de publicaciones
y filtra ÚNICAMENTE aquellas que correspondan a convocatorias, bases, listas de admitidos o noticias relevantes sobre:
1. Policía Nacional (Escala Básica o Ejecutiva).
2. Guardia Civil (Escala de Cabos y Guardias).
3. Policía Local únicamente en la Comunidad de Madrid o en Canarias.
4. Oposiciones de Informática (Cuerpo Superior, Gestión, Técnico Auxiliar de Informática - TAI, o plazas de informática en Madrid/Canarias/Estado).

Criterios adicionales:
- Ignora convocatorias de otras comunidades autónomas.
- Si NINGUNA publicación cumple los criterios, responde exactamente: SIN_NOVEDADES

Publicaciones a analizar:
{texto_recopilado}
"""

# 3. Llamada a Gemini con 3 reintentos automáticos si hay saturación (error 503)
resultado = ""
for intento in range(3):
    try:
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
        )
        resultado = response.text.strip()
        break
    except Exception as e:
        print(f"Intento {intento + 1} fallido por saturación: {e}")
        time.sleep(20)

# 4. Funciones de envío
def enviar_email(contenido):
    remitente = os.environ["EMAIL_ORIGEN"]
    password = os.environ["EMAIL_PASSWORD"]
    destinatario = os.environ["EMAIL_DESTINO"]

    msg = MIMEMultipart()
    msg["From"] = remitente
    msg["To"] = destinatario
    msg["Subject"] = "🚨 Novedades en tus Oposiciones (BOE / BOCM / BOC)"

    cuerpo = f"Se han detectado las siguientes publicaciones que cumplen tus criterios:\n\n{contenido}"
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(remitente, password)
        server.sendmail(remitente, destinatario, msg.as_string())

def enviar_whatsapp(contenido):
    telefono = os.environ["WHATSAPP_PHONE"]
    apikey = os.environ["WHATSAPP_APIKEY"]
    
    texto_wa = f"🚨 *Novedades Oposiciones*\n\n{contenido[:1500]}"
    texto_codificado = urllib.parse.quote(texto_wa)
    
    url = f"https://api.callmebot.com/whatsapp.php?phone={telefono}&text={texto_codificado}&apikey={apikey}"
    requests.get(url, timeout=15)

# 5. Ejecutar envíos solo si hay novedades
if resultado and "SIN_NOVEDADES" not in resultado:
    enviar_email(resultado)
    enviar_whatsapp(resultado)

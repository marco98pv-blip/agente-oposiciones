import os
import time
import smtplib
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import feedparser
import requests
from bs4 import BeautifulSoup
from google import genai

ARCHIVO_HISTORIAL = "historial.txt"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

# 1. Cargar memoria de enlaces ya revisados
def cargar_historial():
    if not os.path.exists(ARCHIVO_HISTORIAL):
        return set()
    with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def guardar_historial(enlaces_totales):
    # Mantiene los últimos 1.500 enlaces para que el archivo no crezca sin límite
    lista_recortada = list(enlaces_totales)[-1500:]
    with open(ARCHIVO_HISTORIAL, "w", encoding="utf-8") as f:
        for enlace in lista_recortada:
            f.write(enlace + "\n")

historial = cargar_historial()
nuevas_entradas = []
nuevos_enlaces = set()

def registrar_entrada(fuente, titulo, enlace):
    enlace = enlace.strip()
    if enlace and enlace not in historial and enlace not in nuevos_enlaces:
        nuevos_enlaces.add(enlace)
        nuevas_entradas.append(f"- [{fuente}] Título: {titulo.strip()} | Enlace: {enlace}")

# 2. Fuentes RSS Oficiales (BOE, BOCM y BOC Canarias)
FEEDS = {
    "BOE": "https://www.boe.es/rss/canal.php?c=opo",
    "BOCM": "https://www.bocm.es/rss",
    "BOC Canarias": "https://www.gobiernodecanarias.org/boc/rss.xml",
}

for nombre_fuente, url in FEEDS.items():
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:40]:
            registrar_entrada(nombre_fuente, entry.title, entry.link)
    except Exception as e:
        print(f"Aviso: No se pudo leer el RSS de {nombre_fuente}: {e}")

# 3. Webs oficiales sin RSS (BOC Sección Personal, Policía Nacional, Guardia Civil)
WEBS_OFICIALES = [
    ("BOC Personal", "https://www.gobiernodecanarias.org/boc/", "https://www.gobiernodecanarias.org"),
    ("Policía Nacional", "https://www.policia.es/_es/oposiciones_seleccion.php", "https://www.policia.es/_es/"),
    ("Guardia Civil", "https://www.guardiacivil.es/es/institucional/serguardia/ingresoguardia/index.html", "https://www.guardiacivil.es"),
]

for nombre_web, url_web, dominio_base in WEBS_OFICIALES:
    try:
        resp = requests.get(url_web, headers=HEADERS, timeout=20)
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            texto = a.get_text(" ", strip=True)
            href = a["href"].strip()
            # Filtramos enlaces vacíos o menús genéricos cortos
            if len(texto) > 20 and not href.startswith(("#", "javascript:", "mailto:")):
                enlace_completo = urllib.parse.urljoin(dominio_base, href)
                registrar_entrada(nombre_web, texto, enlace_completo)
    except Exception as e:
        print(f"Aviso: No se pudo rastrear {nombre_web}: {e}")

# Si no hay ningún enlace nuevo respecto a ejecuciones anteriores, terminamos sin gastar cuota de IA
if not nuevas_entradas:
    print("No hay publicaciones nuevas sin revisar.")
    exit(0)

texto_recopilado = "\n".join(nuevas_entradas)

# 4. Filtrado inteligente con Gemini según tus criterios exactos
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

prompt = f"""
Eres un asistente experto en empleo público en España. Analiza la siguiente lista de publicaciones NUEVAS
y filtra ÚNICAMENTE aquellas que correspondan a convocatorias, apertura de plazos, bases, listas de admitidos o noticias relevantes sobre:

1. Policía Nacional: Escala Básica o Escala Ejecutiva (exclusivamente Turno Libre).
2. Guardia Civil: Escala de Cabos y Guardias (exclusivamente Turno Libre).
3. Policía Local: ÚNICAMENTE en municipios de la Comunidad de Madrid o de Canarias (exclusivamente Turno Libre).
4. Oposiciones de Informática (en la Comunidad de Madrid, en Canarias o ámbito Estatal):
   - ÚNICAMENTE plazas de **Turno Libre** (descarta totalmente Promoción Interna).
   - ÚNICAMENTE plazas del **Grupo C1** (como Técnico Auxiliar de Informática - TAI) o cualquier convocatoria de informática/sistemas/redes que exija titulación de **Bachiller, Técnico Superior (FP de Grado Superior en ASIR o equivalente)**.
   - Descarta plazas de Grupo A1 o A2 que exijan Grado Universitario, Ingeniería o Diplomatura.

Reglas estrictas adicionales:
- Ignora convocatorias de cualquier otra comunidad autónoma que no sea Madrid, Canarias o ámbito Estatal.
- Ignora adjudicaciones finales de destinos o nombramientos antiguos donde ya no haya proceso selectivo activo.

Para cada coincidencia válida, devuelve exactamente este formato limpio:
- **Cuerpo / Plaza:** [Nombre]
- **Ámbito y Grupo:** [Estado / Madrid / Canarias - Grupo/Escala]
- **Resumen:** [1 frase con el trámite: convocatoria, plazo, lista admitidos, etc.]
- **Enlace:** [URL directa]

Si NINGUNA publicación cumple TODOS los criterios anteriores, responde únicamente con la palabra: SIN_NOVEDADES

Publicaciones nuevas a analizar:
{texto_recopilado}
"""

resultado = ""
exito_ia = False

for intento in range(3):
    try:
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
        )
        resultado = response.text.strip()
        exito_ia = True
        break
    except Exception as e:
        print(f"Intento {intento + 1} fallido por saturación: {e}")
        time.sleep(20)

# 5. Funciones de envío
def enviar_email(contenido):
    remitente = os.environ["EMAIL_ORIGEN"]
    password = os.environ["EMAIL_PASSWORD"]
    destinatario = os.environ["EMAIL_DESTINO"]

    msg = MIMEMultipart()
    msg["From"] = remitente
    msg["To"] = destinatario
    msg["Subject"] = "🚨 Novedades en tus Oposiciones (BOE / BOCM / BOC)"

    cuerpo = f"Se han detectado nuevas publicaciones que cumplen tus criterios:\n\n{contenido}"
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

# 6. Enviar avisos y actualizar historial solo si la IA respondió correctamente
if exito_ia:
    if resultado and "SIN_NOVEDADES" not in resultado:
        enviar_email(resultado)
        enviar_whatsapp(resultado)
    
    historial.update(nuevos_enlaces)
    guardar_historial(historial)

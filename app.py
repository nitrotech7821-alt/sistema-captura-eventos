import os
import sqlite3
from datetime import datetime
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
import plotly.express as px

# =====================================================
# CONFIGURACIÓN
# =====================================================
CARPETA_DATOS = "datos_eventos"
CARPETA_ARCHIVOS = os.path.join(CARPETA_DATOS, "archivos")
DB_PATH = os.path.join(CARPETA_DATOS, "eventos.db")
CATALOGO_EXCEL = "Catalogodeinformaciongeoelectoral.xlsx"
LOGO_DIF = "logo_dif.png"

os.makedirs(CARPETA_DATOS, exist_ok=True)
os.makedirs(CARPETA_ARCHIVOS, exist_ok=True)

# =====================================================
# BASE DE DATOS
# =====================================================
def conectar():
    return sqlite3.connect(DB_PATH)


def crear_tablas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_captura TEXT,
            evento TEXT,
            fecha_evento TEXT,
            nombre TEXT,
            direccion TEXT,
            colonia TEXT,
            celular TEXT,
            municipio TEXT,
            localidad TEXT,
            seccion TEXT,
            distrito TEXT,
            latitud TEXT,
            longitud TEXT,
            mapa TEXT,
            fotografia TEXT,
            ine TEXT
        )
    """)

    columnas = [col[1] for col in cur.execute("PRAGMA table_info(registros)").fetchall()]

    nuevas_columnas = {
        "localidad": "TEXT",
        "latitud": "TEXT",
        "longitud": "TEXT",
        "mapa": "TEXT",
        "fotografia": "TEXT",
        "ine": "TEXT"
    }

    for columna, tipo in nuevas_columnas.items():
        if columna not in columnas:
            cur.execute(f"ALTER TABLE registros ADD COLUMN {columna} {tipo}")

    conn.commit()
    conn.close()


def cargar_datos():
    conn = conectar()
    df = pd.read_sql_query("SELECT * FROM registros ORDER BY id DESC", conn)
    conn.close()
    return df


def buscar_registro_por_id(registro_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT * FROM registros WHERE id = ?", (registro_id,))
    fila = cur.fetchone()
    columnas = [desc[0] for desc in cur.description]
    conn.close()

    if not fila:
        return None

    return dict(zip(columnas, fila))


def guardar_registro(datos):
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO registros (
            fecha_captura, evento, fecha_evento, nombre, direccion,
            colonia, celular, municipio, localidad, seccion, distrito,
            latitud, longitud, mapa, fotografia, ine
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, datos)

    conn.commit()
    nuevo_id = cur.lastrowid
    conn.close()
    return nuevo_id


def actualizar_registro(registro_id, datos):
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        UPDATE registros SET
            fecha_captura = ?,
            evento = ?,
            fecha_evento = ?,
            nombre = ?,
            direccion = ?,
            colonia = ?,
            celular = ?,
            municipio = ?,
            localidad = ?,
            seccion = ?,
            distrito = ?,
            latitud = ?,
            longitud = ?,
            mapa = ?,
            fotografia = ?,
            ine = ?
        WHERE id = ?
    """, datos + (registro_id,))

    conn.commit()
    filas = cur.rowcount
    conn.close()
    return filas


def eliminar_registro(registro_id):
    conn = conectar()
    cur = conn.cursor()
    cur.execute("DELETE FROM registros WHERE id = ?", (registro_id,))
    conn.commit()
    filas = cur.rowcount
    conn.close()
    return filas


def existe_duplicado(nombre, celular, evento, excluir_id=None):
    conn = conectar()
    cur = conn.cursor()

    nombre = nombre.upper().strip()
    evento = evento.upper().strip()
    celular = celular.strip()

    if celular:
        query = """
            SELECT id, nombre, celular, evento
            FROM registros
            WHERE (celular = ? OR (nombre = ? AND evento = ?))
        """
        params = [celular, nombre, evento]
    else:
        query = """
            SELECT id, nombre, celular, evento
            FROM registros
            WHERE nombre = ? AND evento = ?
        """
        params = [nombre, evento]

    if excluir_id:
        query += " AND id <> ?"
        params.append(excluir_id)

    query += " LIMIT 1"
    cur.execute(query, params)
    resultado = cur.fetchone()
    conn.close()
    return resultado

# =====================================================
# CATÁLOGO Y MAPA
# =====================================================
@st.cache_data
def cargar_catalogo():
    try:
        df = pd.read_excel(CATALOGO_EXCEL)
        df.columns = df.columns.str.strip().str.upper()
        df["SECCION"] = df["SECCION"].astype(str).str.strip()
        return df
    except Exception as e:
        st.error(f"No se pudo cargar el catálogo electoral: {e}")
        return pd.DataFrame()


def buscar_seccion(seccion):
    catalogo = cargar_catalogo()

    if catalogo.empty or not seccion:
        return None

    seccion = str(seccion).strip()

    try:
        fila = catalogo[catalogo["SECCION"].astype(str).str.strip() == seccion]

        if not fila.empty:
            r = fila.iloc[0]

            distrito = str(r.get("DISTRITO", "")).strip()
            municipio = str(r.get("NOMBRE_M", r.get("NOMBRE_MUNICIPIO", ""))).strip()
            localidad = str(r.get("NOMBRE_LC", r.get("NOMBRE_LOCALIDAD", ""))).strip()

            return {
                "distrito": f"Distrito {distrito}" if distrito else "Pendiente",
                "municipio": municipio,
                "localidad": localidad
            }
    except Exception:
        pass

    return None


def geocodificar_osm(direccion, colonia, municipio):
    direccion_completa = f"{direccion}, {colonia}, {municipio}, Sonora, México"
    url = "https://nominatim.openstreetmap.org/search"

    params = {
        "q": direccion_completa,
        "format": "json",
        "limit": 1
    }

    headers = {
        "User-Agent": "SistemaEventosDIF/1.0"
    }

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()

        if data:
            return data[0]["lat"], data[0]["lon"]
    except Exception:
        pass

    return "", ""


def crear_link_mapa(latitud, longitud, direccion, colonia, municipio):
    if latitud and longitud:
        return f"https://www.openstreetmap.org/?mlat={latitud}&mlon={longitud}#map=17/{latitud}/{longitud}"

    texto = quote_plus(f"{direccion} {colonia} {municipio} Sonora México")
    return f"https://www.openstreetmap.org/search?query={texto}"


def guardar_archivo(archivo, tipo):
    if archivo is None:
        return ""

    nombre = archivo.name.replace(" ", "_")
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = os.path.join(CARPETA_ARCHIVOS, f"{tipo}_{fecha}_{nombre}")

    with open(ruta, "wb") as f:
        f.write(archivo.getbuffer())

    return ruta

# =====================================================
# DISEÑO
# =====================================================
def aplicar_diseno():
    st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(135deg, #EEF8F5 0%, #FFF7E7 52%, #F8C2A5 100%);
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #087B75, #0F5F5B);
    }
    section[data-testid="stSidebar"] * {
        color: white !important;
    }
    .main-title {
        color:#087B75;
        font-size:42px;
        font-weight:900;
        text-align:center;
        margin-bottom:4px;
    }
    .subtitle {
        text-align:center;
        color:#374151;
        font-size:18px;
        margin-bottom:25px;
    }
    .card {
        background:rgba(255,255,255,.84);
        padding:24px;
        border-radius:20px;
        box-shadow:0 8px 22px rgba(0,0,0,.10);
        border-left:8px solid #087B75;
        margin-bottom:22px;
    }
    .metric-card {
        background:linear-gradient(135deg, rgba(219,246,241,.95), rgba(255,242,216,.95));
        padding:20px;
        border-radius:18px;
        box-shadow:0 6px 16px rgba(0,0,0,.10);
        text-align:center;
        margin-bottom:12px;
    }
    .metric-number {
        color:#087B75;
        font-size:34px;
        font-weight:900;
    }
    .metric-label {
        color:#374151;
        font-size:15px;
        font-weight:700;
    }
    .stButton > button, .stFormSubmitButton > button {
        background: linear-gradient(90deg, #E94E1B, #F2B233);
        color:white;
        border:none;
        border-radius:14px;
        padding:12px 18px;
        font-weight:900;
        box-shadow:0 6px 16px rgba(0,0,0,.18);
    }
    .stDownloadButton > button {
        background: linear-gradient(90deg, #087B75, #14A39A);
        color:white;
        border:none;
        border-radius:14px;
        font-weight:800;
    }
    </style>
    """, unsafe_allow_html=True)


def mostrar_encabezado():
    if os.path.exists("logo_dif.png"):
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            st.image("logo_dif.png", use_container_width=True)

    st.markdown('<div class="main-title">Sistema de Captura de Datos y Eventos</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Captura, foto, INE, distrito automático por sección, reportes, gráficas y mapa gratuito.</div>', unsafe_allow_html=True)


def valor_registro(campo, defecto=""):
    reg = st.session_state.get("registro_cargado") or {}
    return str(reg.get(campo, defecto) or defecto)


def fecha_registro():
    texto = valor_registro("fecha_evento", "")
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except Exception:
        return datetime.now().date()

# =====================================================
# INICIO
# =====================================================
crear_tablas()

st.set_page_config(page_title="Sistema de Captura de Eventos", layout="wide")
aplicar_diseno()
mostrar_encabezado()

if "registro_cargado" not in st.session_state:
    st.session_state.registro_cargado = None
if "id_actual" not in st.session_state:
    st.session_state.id_actual = None

menu = st.sidebar.radio(
    "Menú",
    [
        "Registro de captura",
        "Reporteador",
        "Gráficas",
        "Buscar persona"
    ]
)

# =====================================================
# CAPTURA / NUEVO / MODIFICAR / ELIMINAR
# =====================================================
if menu == "Registro de captura":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.header("📝 Persona capturar")

    st.subheader("Gestión de registro")
    c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1])

    with c1:
        id_buscar = st.number_input("ID para modificar/eliminar", min_value=0, step=1, value=int(st.session_state.id_actual or 0))

    with c2:
        if st.button("🔎 Cargar ID"):
            if id_buscar <= 0:
                st.warning("Escribe un ID válido.")
            else:
                reg = buscar_registro_por_id(int(id_buscar))
                if reg:
                    st.session_state.registro_cargado = reg
                    st.session_state.id_actual = int(id_buscar)
                    st.success(f"Registro ID {id_buscar} cargado para modificar.")
                    st.rerun()
                else:
                    st.error("No se encontró ese ID.")

    with c3:
        if st.button("🆕 Nuevo"):
            st.session_state.registro_cargado = None
            st.session_state.id_actual = None
            st.success("Formulario listo para nuevo registro.")
            st.rerun()

    with c4:
        if st.button("🗑️ Eliminar"):
            if id_buscar <= 0:
                st.warning("Escribe el ID que deseas eliminar.")
            else:
                filas = eliminar_registro(int(id_buscar))
                if filas:
                    st.session_state.registro_cargado = None
                    st.session_state.id_actual = None
                    st.success(f"Registro ID {id_buscar} eliminado correctamente.")
                    st.rerun()
                else:
                    st.error("No se encontró ese ID.")

    if st.session_state.id_actual:
        st.info(f"Editando registro ID: {st.session_state.id_actual}")
    else:
        st.info("Modo: Nuevo registro")

    with st.form("form_registro"):
        col1, col2 = st.columns(2)

        with col1:
            evento = st.text_input("Evento", value=valor_registro("evento"))
            fecha_evento = st.date_input("Fecha del evento", value=fecha_registro())
            nombre = st.text_input("Nombre completo", value=valor_registro("nombre"))
            direccion = st.text_area("Dirección", value=valor_registro("direccion"))
            colonia = st.text_input("Colonia", value=valor_registro("colonia"))

        with col2:
            celular = st.text_input("Celular", value=valor_registro("celular"))
            seccion = st.text_input("Sección", value=valor_registro("seccion"))

            info_seccion = buscar_seccion(seccion)

            if info_seccion:
                municipio = info_seccion["municipio"]
                localidad = info_seccion["localidad"]
                distrito = info_seccion["distrito"]
            else:
                municipio = valor_registro("municipio")
                localidad = valor_registro("localidad")
                distrito = valor_registro("distrito", "Pendiente") or "Pendiente"

            st.text_input("Municipio automático", value=municipio, disabled=True)
            st.text_input("Localidad automática", value=localidad, disabled=True)
            st.text_input("Distrito automático", value=distrito, disabled=True)

        fotografia = st.file_uploader("Fotografía", type=["jpg", "jpeg", "png"])
        ine = st.file_uploader("INE", type=["jpg", "jpeg", "png", "pdf"])

        b1, b2 = st.columns(2)
        with b1:
            guardar_nuevo = st.form_submit_button("💾 Guardar nuevo registro")
        with b2:
            modificar = st.form_submit_button("✏️ Modificar registro cargado")

        if guardar_nuevo or modificar:
            if not nombre or not evento:
                st.error("Nombre y evento son obligatorios.")
            elif modificar and not st.session_state.id_actual:
                st.error("Primero carga un registro por ID para poder modificarlo.")
            else:
                excluir_id = st.session_state.id_actual if modificar else None
                duplicado = existe_duplicado(nombre, celular, evento, excluir_id=excluir_id)

                if duplicado:
                    st.error("⚠️ Esta persona ya fue registrada anteriormente.")
                    st.write(f"Registro existente ID: {duplicado[0]}")
                    st.write(f"Nombre: {duplicado[1]}")
                    st.write(f"Celular: {duplicado[2]}")
                    st.write(f"Evento: {duplicado[3]}")
                else:
                    latitud, longitud = geocodificar_osm(direccion, colonia, municipio)
                    mapa = crear_link_mapa(latitud, longitud, direccion, colonia, municipio)

                    ruta_foto = guardar_archivo(fotografia, "foto")
                    ruta_ine = guardar_archivo(ine, "ine")

                    if modificar:
                        registro_actual = st.session_state.get("registro_cargado") or {}
                        if not ruta_foto:
                            ruta_foto = registro_actual.get("fotografia", "")
                        if not ruta_ine:
                            ruta_ine = registro_actual.get("ine", "")

                    datos = (
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        evento.upper(),
                        str(fecha_evento),
                        nombre.upper(),
                        direccion.upper(),
                        colonia.upper(),
                        celular,
                        municipio.upper(),
                        localidad.upper(),
                        seccion,
                        distrito,
                        latitud,
                        longitud,
                        mapa,
                        ruta_foto,
                        ruta_ine
                    )

                    if guardar_nuevo:
                        nuevo_id = guardar_registro(datos)
                        st.success(f"✅ Registro guardado correctamente. ID generado: {nuevo_id}")
                    else:
                        filas = actualizar_registro(st.session_state.id_actual, datos)
                        if filas:
                            st.success(f"✅ Registro ID {st.session_state.id_actual} modificado correctamente.")
                        else:
                            st.error("No se pudo modificar el registro.")

                    if info_seccion:
                        st.info(f"Sección encontrada: {seccion} | {distrito} | {municipio} | {localidad}")
                    else:
                        st.warning("No se encontró esa sección en el catálogo. Se guardó como Pendiente.")

                    if latitud and longitud:
                        st.info(f"Coordenadas encontradas: {latitud}, {longitud}")
                        mapa_df = pd.DataFrame({"lat": [float(latitud)], "lon": [float(longitud)]})
                        st.subheader("📍 Mapa de ubicación")
                        st.map(mapa_df)
                    else:
                        st.warning("No se encontraron coordenadas exactas. Se guardó el enlace de búsqueda.")

                    st.link_button("🌎 Abrir ubicación en OpenStreetMap", mapa)

    st.markdown('</div>', unsafe_allow_html=True)

# =====================================================
# REPORTEADOR
# =====================================================
elif menu == "Reporteador":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.header("📊 Reporteador")

    df = cargar_datos()

    if df.empty:
        st.warning("Todavía no hay registros.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(f'<div class="metric-card"><div class="metric-number">{len(df)}</div><div class="metric-label">Total registros</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card"><div class="metric-number">{df["evento"].nunique()}</div><div class="metric-label">Eventos</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="metric-card"><div class="metric-number">{df["distrito"].nunique()}</div><div class="metric-label">Distritos</div></div>', unsafe_allow_html=True)
        with c4:
            st.markdown(f'<div class="metric-card"><div class="metric-number">{df["colonia"].nunique()}</div><div class="metric-label">Colonias</div></div>', unsafe_allow_html=True)

        col1, col2, col3 = st.columns(3)

        with col1:
            eventos = ["Todos"] + sorted(df["evento"].dropna().unique().tolist())
            evento_sel = st.selectbox("Evento", eventos)

        with col2:
            municipios = ["Todos"] + sorted(df["municipio"].dropna().unique().tolist())
            municipio_sel = st.selectbox("Municipio", municipios)

        with col3:
            distritos = ["Todos"] + sorted(df["distrito"].dropna().unique().tolist())
            distrito_sel = st.selectbox("Distrito", distritos)

        df_filtrado = df.copy()

        if evento_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["evento"] == evento_sel]
        if municipio_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["municipio"] == municipio_sel]
        if distrito_sel != "Todos":
            df_filtrado = df_filtrado[df_filtrado["distrito"] == distrito_sel]

        st.metric("Total de asistentes filtrados", len(df_filtrado))
        st.dataframe(df_filtrado, use_container_width=True)

        excel_path = os.path.join(CARPETA_DATOS, "reporte_asistentes.xlsx")
        df_filtrado.to_excel(excel_path, index=False)

        with open(excel_path, "rb") as f:
            st.download_button(
                "📥 Descargar reporte Excel",
                data=f,
                file_name="reporte_asistentes.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

    st.markdown('</div>', unsafe_allow_html=True)

# =====================================================
# GRÁFICAS
# =====================================================
elif menu == "Gráficas":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.header("📈 Gráficas")

    df = cargar_datos()

    if df.empty:
        st.warning("Todavía no hay registros.")
    else:
        colonias = df["colonia"].value_counts().reset_index()
        colonias.columns = ["Colonia", "Asistentes"]
        st.plotly_chart(px.bar(colonias, x="Colonia", y="Asistentes", title="Colonias con más asistencia"), use_container_width=True)

        municipios = df["municipio"].value_counts().reset_index()
        municipios.columns = ["Municipio", "Asistentes"]
        st.plotly_chart(px.pie(municipios, names="Municipio", values="Asistentes", title="Asistencia por municipio"), use_container_width=True)

        distritos = df["distrito"].value_counts().reset_index()
        distritos.columns = ["Distrito", "Asistentes"]
        st.plotly_chart(px.bar(distritos, x="Distrito", y="Asistentes", title="Asistencia por distrito"), use_container_width=True)

        eventos = df["evento"].value_counts().reset_index()
        eventos.columns = ["Evento", "Asistentes"]
        st.plotly_chart(px.bar(eventos, x="Evento", y="Asistentes", title="Asistentes por evento"), use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

# =====================================================
# BUSCAR PERSONA
# =====================================================
elif menu == "Buscar persona":
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.header("🔎 Buscar persona")

    df = cargar_datos()

    if df.empty:
        st.warning("Todavía no hay registros.")
    else:
        busqueda = st.text_input("Buscar por nombre, celular, colonia, sección, distrito, evento o ID")

        if busqueda:
            b = busqueda.upper()
            resultado = df[
                df["id"].astype(str).str.contains(b, case=False, na=False) |
                df["nombre"].astype(str).str.contains(b, case=False, na=False) |
                df["celular"].astype(str).str.contains(b, case=False, na=False) |
                df["colonia"].astype(str).str.contains(b, case=False, na=False) |
                df["seccion"].astype(str).str.contains(b, case=False, na=False) |
                df["distrito"].astype(str).str.contains(b, case=False, na=False) |
                df["evento"].astype(str).str.contains(b, case=False, na=False)
            ]

            st.write(f"Resultados encontrados: {len(resultado)}")
            st.dataframe(resultado, use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)

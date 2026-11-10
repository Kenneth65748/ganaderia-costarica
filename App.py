import streamlit as st
import pandas as pd

# =====================================================================
# ADAPTADOR A TURSO (AGREGADO)
# Hace que el resto del código siga usando "sqlite3" exactamente igual,
# pero los datos se guardan en Turso (nube) y ya no se pierden cuando
# Streamlit reinicia la app. Los datos de conexión van en Secrets.
# =====================================================================
import os
import tempfile
from datetime import date
from types import SimpleNamespace
import sqlite3 as _sqlite3_real
import requests


class _IntegrityError(_sqlite3_real.IntegrityError):
    pass


class _OperationalError(_sqlite3_real.OperationalError):
    pass


@st.cache_resource
def _estado_turso():
    return {"sesion": requests.Session(), "ddl": set()}


def _credenciales():
    try:
        url = st.secrets["TURSO_URL"].strip()
        token = st.secrets["TURSO_TOKEN"].strip()
    except Exception:
        raise RuntimeError("Faltan TURSO_URL y TURSO_TOKEN en Secrets de Streamlit.")
    if url.startswith("libsql://"):
        url = "https://" + url[len("libsql://"):]
    return url.rstrip("/"), token


def _a_argumento(valor):
    if valor is None:
        return {"type": "null"}
    if isinstance(valor, bool):
        return {"type": "integer", "value": str(int(valor))}
    if isinstance(valor, int):
        return {"type": "integer", "value": str(valor)}
    if isinstance(valor, float):
        return {"type": "float", "value": valor}
    return {"type": "text", "value": str(valor)}


def _de_celda(celda):
    tipo = celda.get("type")
    if tipo == "null":
        return None
    valor = celda.get("value")
    if tipo == "integer":
        return int(valor)
    if tipo == "float":
        return float(valor)
    return valor


def _enviar(sentencias):
    """Envía sentencias SQL a Turso. Devuelve una lista de (columnas, filas)."""
    url, token = _credenciales()
    pedidos = [
        {"type": "execute", "stmt": {"sql": sql, "args": [_a_argumento(p) for p in params]}}
        for sql, params in sentencias
    ]
    pedidos.append({"type": "close"})
    try:
        respuesta = _estado_turso()["sesion"].post(
            url + "/v2/pipeline",
            json={"requests": pedidos},
            headers={"Authorization": "Bearer " + token},
            timeout=30,
        )
    except requests.RequestException as e:
        raise _OperationalError(f"No se pudo conectar con la base de datos: {e}")
    if respuesta.status_code != 200:
        raise _OperationalError(f"La base de datos respondió con error {respuesta.status_code}: {respuesta.text[:200]}")
    resultados = []
    for item in respuesta.json()["results"][:len(sentencias)]:
        if item["type"] == "error":
            mensaje = item["error"].get("message", "Error desconocido")
            if "UNIQUE" in mensaje.upper():
                raise _IntegrityError(mensaje)
            raise _OperationalError(mensaje)
        resultado = item["response"]["result"]
        columnas = [c.get("name") for c in resultado.get("cols", [])]
        filas = [tuple(_de_celda(c) for c in fila) for fila in resultado["rows"]]
        resultados.append((columnas, filas))
    return resultados


class _Cursor:
    def __init__(self):
        self._filas = []
        self._pos = 0
        self.description = None

    def execute(self, sql, params=()):
        texto = sql.strip()
        clave = " ".join(texto.split())
        es_ddl = clave.upper().startswith(("CREATE TABLE IF NOT EXISTS", "ALTER TABLE"))
        estado = _estado_turso()
        self._filas, self._pos, self.description = [], 0, None
        if es_ddl and clave in estado["ddl"]:
            return self
        try:
            columnas, filas = _enviar([(texto, tuple(params))])[0]
        except _OperationalError as e:
            if es_ddl and "duplicate column" in str(e).lower():
                estado["ddl"].add(clave)
            raise
        if es_ddl:
            estado["ddl"].add(clave)
        self._filas = filas
        self.description = tuple((c, None, None, None, None, None, None) for c in columnas) if columnas else None
        return self

    def fetchone(self):
        if self._pos < len(self._filas):
            fila = self._filas[self._pos]
            self._pos += 1
            return fila
        return None

    def fetchall(self):
        restantes = self._filas[self._pos:]
        self._pos = len(self._filas)
        return restantes


class _Conexion:
    def cursor(self):
        return _Cursor()

    def commit(self):
        pass  # Turso guarda cada instrucción automáticamente

    def close(self):
        pass


sqlite3 = SimpleNamespace(
    connect=lambda *args, **kwargs: _Conexion(),
    IntegrityError=_IntegrityError,
    OperationalError=_OperationalError,
    Error=_sqlite3_real.Error,
)

_SQL_ANIMALES = """
    CREATE TABLE IF NOT EXISTS animales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        arete TEXT UNIQUE NOT NULL,
        fecha_compra TEXT NOT NULL,
        peso_compra REAL NOT NULL,
        precio_kilo_compra REAL NOT NULL,
        transporte_compra REAL DEFAULT 10000.0,
        precio_compra REAL NOT NULL,
        estado TEXT DEFAULT 'En engorde',
        fecha_venta TEXT,
        peso_venta REAL,
        precio_kilo_venta REAL,
        transporte_venta REAL DEFAULT 10000.0,
        precio_venta REAL
    )
"""

_SQL_SOCIOS = """
    CREATE TABLE IF NOT EXISTS socios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        porcentaje REAL NOT NULL
    )
"""

_COLUMNAS_ANIMALES = [
    "id", "arete", "fecha_compra", "peso_compra", "precio_kilo_compra",
    "transporte_compra", "precio_compra", "estado", "fecha_venta",
    "peso_venta", "precio_kilo_venta", "transporte_venta", "precio_venta",
]


def _migrar_datos_iniciales():
    """Una sola vez: pasa a Turso los animales del archivo ganaderia.db de GitHub."""
    _enviar([("CREATE TABLE IF NOT EXISTS _migracion (clave TEXT PRIMARY KEY)", ())])
    hecho = _enviar([("SELECT COUNT(*) FROM _migracion WHERE clave = ?", ("ganaderia.db",))])[0][1][0][0]
    if hecho:
        return
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ganaderia.db")
    if os.path.exists(ruta):
        filas, nombres = [], []
        con = _sqlite3_real.connect(ruta)
        try:
            cur = con.cursor()
            cur.execute("SELECT * FROM animales")
            filas = cur.fetchall()
            nombres = [d[0] for d in cur.description]
        except _sqlite3_real.Error:
            filas, nombres = [], []
        finally:
            con.close()
        if filas:
            _enviar([(_SQL_ANIMALES, ())])
            usar = [i for i, n in enumerate(nombres) if n in _COLUMNAS_ANIMALES and n != "id"]
            columnas_ins = ", ".join(nombres[i] for i in usar)
            marcas = ", ".join("?" for _ in usar)
            sql_ins = f"INSERT OR IGNORE INTO animales ({columnas_ins}) VALUES ({marcas})"
            lote = []
            for fila in filas:
                lote.append((sql_ins, tuple(fila[i] for i in usar)))
                if len(lote) == 50:
                    _enviar(lote)
                    lote = []
            if lote:
                _enviar(lote)
    _enviar([("INSERT OR IGNORE INTO _migracion (clave) VALUES (?)", ("ganaderia.db",))])


def _crear_respaldo():
    """Arma un archivo .db de SQLite con todos los datos actuales."""
    conexion = sqlite3.connect("ganaderia.db")
    cursor = conexion.cursor()
    cursor.execute("SELECT " + ", ".join(_COLUMNAS_ANIMALES) + " FROM animales ORDER BY id")
    animales = cursor.fetchall()
    cursor.execute("SELECT id, nombre, porcentaje FROM socios ORDER BY id")
    socios = cursor.fetchall()
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = os.path.join(carpeta, "respaldo.db")
        con = _sqlite3_real.connect(ruta)
        con.execute(_SQL_ANIMALES)
        con.execute(_SQL_SOCIOS)
        marcas = ", ".join("?" for _ in _COLUMNAS_ANIMALES)
        con.executemany(
            "INSERT INTO animales (" + ", ".join(_COLUMNAS_ANIMALES) + ") VALUES (" + marcas + ")",
            animales,
        )
        con.executemany("INSERT INTO socios (id, nombre, porcentaje) VALUES (?, ?, ?)", socios)
        con.commit()
        con.close()
        with open(ruta, "rb") as f:  # <-- Asegúrate de usar 'f' aquí
            return f.read()         # <-- Y 'f.read()' aquí
# =====================================================================
# FIN DEL ADAPTADOR. Desde aquí, el código original sin cambios.
# =====================================================================

# Configuración de la página web
st.set_page_config(
    page_title="Gestión Ganadera de Engorde",
    page_icon="🐄",
    layout="wide"
)

# --- ESTILO DE FONDO PERSONALIZADO ---
st.markdown(
    """
    <style>
    /* Imagen de fondo para toda la aplicación */
    .stApp {
        background-image: url("https://images.unsplash.com/photo-1500595046743-cd271d694d30?q=80&w=1920&auto=format&fit=crop");
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
    }

    /* Fondo semitransparente en los contenedores para que las letras y números resalten perfectamente */
    .block-container {
        background-color: rgba(15, 23, 42, 0.88);
        padding: 2rem;
        border-radius: 15px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- MIGRACIÓN ÚNICA A TURSO (AGREGADO) ---
try:
    _migrar_datos_iniciales()
except Exception as _error_turso:
    st.error(f"No se pudo conectar con la base de datos en Turso. Revise los Secrets. Detalle: {_error_turso}")
    st.stop()

# Inicializar Base de Datos con columnas de transporte
def inicializar_base_datos():
    conexion = sqlite3.connect("ganaderia.db")
    cursor = conexion.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS animales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arete TEXT UNIQUE NOT NULL,
            fecha_compra TEXT NOT NULL,
            peso_compra REAL NOT NULL,
            precio_kilo_compra REAL NOT NULL,
            transporte_compra REAL DEFAULT 10000.0,
            precio_compra REAL NOT NULL,
            estado TEXT DEFAULT 'En engorde',
            fecha_venta TEXT,
            peso_venta REAL,
            precio_kilo_venta REAL,
            transporte_venta REAL DEFAULT 10000.0,
            precio_venta REAL
        )
    """)
    # Asegurar compatibilidad si la base de datos ya existía sin columnas de transporte
    try:
        cursor.execute("ALTER TABLE animales ADD COLUMN transporte_compra REAL DEFAULT 10000.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE animales ADD COLUMN transporte_venta REAL DEFAULT 10000.0")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS socios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            porcentaje REAL NOT NULL
        )
    """)
    cursor.execute("SELECT COUNT(*) FROM socios")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO socios (nombre, porcentaje) VALUES ('Socio Principal', 45.0)")
        cursor.execute("INSERT INTO socios (nombre, porcentaje) VALUES ('Socio Secundario', 55.0)")
    conexion.commit()
    conexion.close()

inicializar_base_datos()

# --- MENÚ LATERAL ---
st.sidebar.title("🐄 Menú Ganadero")
menu = st.sidebar.selectbox(
    "Seleccione una sección:",
    ["📊 Dashboard e Indicadores", "📥 Registrar Compra", "📤 Registrar Venta", "📋 Inventario General", "🗑️ Eliminar / Corregir"]
)

# --- RESPALDO DE DATOS (AGREGADO) ---
with st.sidebar.expander("💾 Respaldo de datos"):
    st.caption("Descargue una copia de todos los datos y guárdela en la computadora o en Google Drive.")
    if st.button("Preparar respaldo"):
        st.session_state["respaldo_bytes"] = _crear_respaldo()
        st.session_state["respaldo_fecha"] = date.today().isoformat()
    if "respaldo_bytes" in st.session_state:
        st.download_button(
            "⬇️ Descargar respaldo (.db)",
            data=st.session_state["respaldo_bytes"],
            file_name=f"ganaderia_respaldo_{st.session_state['respaldo_fecha']}.db",
            mime="application/octet-stream",
        )

# --- 1. DASHBOARD ---
if menu == "📊 Dashboard e Indicadores":
    st.title("📊 Panel de Control y Resumen Financiero")
    st.markdown("Indicadores operativos, control de transportes, capital y reparto de utilidades en tiempo real.")
    st.markdown("---")

    conexion = sqlite3.connect("ganaderia.db")
    cursor = conexion.cursor()

    cursor.execute("SELECT COUNT(*) FROM animales WHERE estado = 'En engorde'")
    en_engorde = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM animales WHERE estado = 'Vendido'")
    vendidos = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(precio_compra) FROM animales")
    total_invertido = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(transporte_compra), SUM(transporte_venta) FROM animales")
    fletes_c_todo, fletes_v_todo = cursor.fetchone()
    total_transportes_general = (fletes_c_todo or 0.0) + (fletes_v_todo or 0.0)

    cursor.execute("SELECT SUM(precio_venta) FROM animales WHERE estado = 'Vendido'")
    ingresos_ventas = cursor.fetchone()[0] or 0.0

    # Ganancia total = Venta total (con flete) - Inversión total de los animales vendidos (con flete)
    cursor.execute("""
        SELECT SUM(precio_venta - precio_compra)
        FROM animales WHERE estado = 'Vendido'
    """)
    ganancia_total_ventas = cursor.fetchone()[0] or 0.0

    # Capital base puro de los animales (precio_compra total menos el transporte de compra)
    cursor.execute("SELECT SUM(precio_compra - transporte_compra) FROM animales")
    capital_base_animales = cursor.fetchone()[0] or 0.0

    # Fletes específicos de animales vendidos para devolución por socio
    cursor.execute("SELECT SUM(transporte_compra) FROM animales WHERE estado = 'Vendido'")
    flete_compra_vendidos = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT SUM(transporte_venta) FROM animales WHERE estado = 'Vendido'")
    flete_venta_vendidos = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT nombre, porcentaje FROM socios")
    socios = cursor.fetchall()
    conexion.close()

    # Sección 1: Estado Actual
    st.subheader("🐄 Estado Actual")
    col1, col2, col3 = st.columns(3)
    col1.metric("Animales en Engorde", f"{en_engorde} cabezas", "Activos en finca")
    col2.metric("Animales Vendidos", f"{vendidos} cabezas", "Historial de salida")
    col3.metric("Total Invertido (Con Fletes)", f"₡{total_invertido:,.2f}", "Capital inicial + Transporte de compra")

    st.markdown("")

    # Sección 2: Rendimiento Comercial y Transportes
    st.subheader("💰 Rendimiento Comercial y Transportes")
    col4, col5, col6 = st.columns(3)
    col4.metric("Ingresos Totales por Ventas", f"₡{ingresos_ventas:,.2f}", "Ventas más flete de salida")
    col5.metric("Línea de Transportes (Fletes)", f"₡{total_transportes_general:,.2f}", "Acumulado de transporte de compra y venta")
    col6.metric("Ganancia Neta (Aumento)", f"₡{ganancia_total_ventas:,.2f}", "Incremento neto con fletes incluidos")

    st.markdown("---")

    # Sección 3: Liquidación y Reparto entre Socios
    st.subheader("👥 Liquidación y Reparto entre Socios")
    st.markdown("Devolución de capital base y flete de compra para el socio principal, flete de venta para el socio secundario, y distribución de la ganancia neta (45% y 55%):")

    s_col1, s_col2 = st.columns(2)
    for nombre, porcentaje in socios:
        ganancia_socio = ganancia_total_ventas * (porcentaje / 100.0)

        if "Principal" in nombre:
            monto_total_socio = capital_base_animales + ganancia_socio + flete_compra_vendidos
            s_col1.metric(
                f"Socia: {nombre} ({porcentaje}%)",
                f"₡{monto_total_socio:,.2f}",
                f"Capital (₡{capital_base_animales:,.2f}) + Ganancia (₡{ganancia_socio:,.2f}) + Flete Compra (₡{flete_compra_vendidos:,.2f})"
            )
        else:
            monto_total_socio = ganancia_socio + flete_venta_vendidos
            s_col2.metric(
                f"Socio: {nombre} ({porcentaje}%)",
                f"₡{monto_total_socio:,.2f}",
                f"Ganancia (₡{ganancia_socio:,.2f}) + Flete Venta (₡{flete_venta_vendidos:,.2f})"
            )

# --- 2. REGISTRAR COMPRA ---
elif menu == "📥 Registrar Compra":
    st.title("📥 Registrar Compra de Animal")
    st.markdown("Ingrese los datos de compra. El costo total suma el valor base del animal más el transporte de compra (₡10,000 por defecto).")

    with st.form("form_compra", clear_on_submit=True):
        arete = st.text_input("Número de Arete (Identificador único)")
        fecha_compra = st.date_input("Fecha de Adquisición")
        peso_compra = st.number_input("Peso de Compra (kg)", min_value=0.0, format="%.2f")
        precio_kilo_compra = st.number_input("Precio por Kilo de Compra (₡)", min_value=0.0, format="%.2f")
        transporte_compra = st.number_input("Costo de Transporte / Flete Compra (₡) [Suma]", min_value=0.0, format="%.2f", value=10000.0)

        submitted = st.form_submit_button("Guardar Registro de Compra")
        if submitted:
            if not arete.strip():
                st.error("El número de arete no puede estar vacío.")
            else:
                costo_animal = peso_compra * precio_kilo_compra
                total_compra = costo_animal + transporte_compra
                try:
                    conexion = sqlite3.connect("ganaderia.db")
                    cursor = conexion.cursor()
                    cursor.execute("""
                        INSERT INTO animales (arete, fecha_compra, peso_compra, precio_kilo_compra, transporte_compra, precio_compra, estado)
                        VALUES (?, ?, ?, ?, ?, ?, 'En engorde')
                    """, (arete.strip(), str(fecha_compra), peso_compra, precio_kilo_compra, transporte_compra, total_compra))
                    conexion.commit()
                    conexion.close()
                    st.success(f"¡Animal arete {arete} registrado! Costo base: ₡{costo_animal:,.2f} + Flete: ₡{transporte_compra:,.2f} = Total Entrada: ₡{total_compra:,.2f}")
                except sqlite3.IntegrityError:
                    st.error("¡Error! Ya existe un animal registrado con ese mismo número de arete.")

# --- 3. REGISTRAR VENTA ---
elif menu == "📤 Registrar Venta":
    st.title("📤 Registrar Venta de Animal")
    st.markdown("Seleccione el arete, ingrese los datos de venta y el transporte de salida (flete) que se suma al total de salida.")

    conexion = sqlite3.connect("ganaderia.db")
    cursor = conexion.cursor()
    cursor.execute("SELECT arete FROM animales WHERE estado = 'En engorde'")
    aretes_disponibles = [row[0] for row in cursor.fetchall()]
    conexion.close()

    if not aretes_disponibles:
        st.warning("No hay animales actualmente en etapa de engorde disponibles para la venta.")
    else:
        with st.form("form_venta", clear_on_submit=True):
            arete_seleccionado = st.selectbox("Seleccione el Arete a comercializar", aretes_disponibles)
            fecha_venta = st.date_input("Fecha de Venta")
            peso_venta = st.number_input("Peso de Venta (kg)", min_value=0.0, format="%.2f")
            precio_kilo_venta = st.number_input("Precio por Kilo de Venta (₡)", min_value=0.0, format="%.2f")
            transporte_venta = st.number_input("Costo de Transporte / Flete Venta (₡) [Suma]", min_value=0.0, format="%.2f", value=10000.0)

            submitted_v = st.form_submit_button("Procesar Venta")
            if submitted_v:
                bruto_venta = peso_venta * precio_kilo_venta
                total_venta = bruto_venta + transporte_venta
                conexion = sqlite3.connect("ganaderia.db")
                cursor = conexion.cursor()
                cursor.execute("""
                    UPDATE animales
                    SET estado = 'Vendido', fecha_venta = ?, peso_venta = ?, precio_kilo_venta = ?, transporte_venta = ?, precio_venta = ?
                    WHERE arete = ?
                """, (str(fecha_venta), peso_venta, precio_kilo_venta, transporte_venta, total_venta, arete_seleccionado))
                conexion.commit()
                conexion.close()
                st.success(f"¡Venta procesada para el arete {arete_seleccionado}! Bruto: ₡{bruto_venta:,.2f} + Flete: ₡{transporte_venta:,.2f} = Total Salida: ₡{total_venta:,.2f}")

# --- 4. INVENTARIO GENERAL ---
elif menu == "📋 Inventario General":
    st.title("📋 Inventario General de Animales")
    st.markdown("Detalle completo de compras, fletes y ventas registrados en el sistema.")

    conexion = sqlite3.connect("ganaderia.db")
    cursor = conexion.cursor()
    cursor.execute("SELECT arete, estado, fecha_compra, peso_compra, precio_kilo_compra, transporte_compra, precio_compra, fecha_venta, peso_venta, precio_kilo_venta, transporte_venta, precio_venta FROM animales")
    filas = cursor.fetchall()
    conexion.close()

    if not filas:
        st.info("Aún no se registran animales en la base de datos.")
    else:
        df = pd.DataFrame(filas, columns=[
            "Arete", "Estado", "F. Compra", "Peso Compra", "₡/kg Compra", "Flete Compra", "Total Compra",
            "F. Venta", "Peso Venta", "₡/kg Venta", "Flete Venta", "Total Venta"
        ])
        st.dataframe(df, use_container_width=True)

# --- 5. ELIMINAR / CORREGIR ---
elif menu == "🗑️ Eliminar / Corregir":
    st.title("🗑️ Corrección y Eliminación de Registros")
    st.markdown("Herramienta administrativa para corregir errores borrando el registro de un animal.")

    conexion = sqlite3.connect("ganaderia.db")
    cursor = conexion.cursor()
    cursor.execute("SELECT arete FROM animales")
    todos_aretes = [row[0] for row in cursor.fetchall()]
    conexion.close()

    if not todos_aretes:
        st.info("No hay registros disponibles para eliminar.")
    else:
        arete_a_borrar = st.selectbox("Seleccione el número de arete que desea eliminar", todos_aretes)
        if st.button("Eliminar Registro del Sistema", type="primary"):
            conexion = sqlite3.connect("ganaderia.db")
            cursor = conexion.cursor()
            cursor.execute("DELETE FROM animales WHERE arete = ?", (arete_a_borrar,))
            conexion.commit()
            conexion.close()
            st.success(f"¡El registro del arete {arete_a_borrar} ha sido eliminado permanentemente!")
            st.rerun()

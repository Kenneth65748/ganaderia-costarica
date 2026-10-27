import streamlit as st
import sqlite3
import pandas as pd

# Configuración de la página web
st.set_page_config(
    page_title="Gestión Ganadera de Engorde",
    page_icon="🐄",
    layout="wide"
)

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

    cursor.execute("SELECT nombre, porcentaje FROM socios")
    socios = cursor.fetchall()
    conexion.close()

    # Cálculo de reconocimiento de fletes por animal vendido (10k para cada socio)
    reconocimiento_flete_socio1 = vendidos * 10000.0
    reconocimiento_flete_socio2 = vendidos * 10000.0

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
    st.markdown("Devolución de capital, reconocimiento de ₡10,000 de flete para cada socio, y distribución del aumento (45% y 55%):")

    s_col1, s_col2 = st.columns(2)
    for nombre, porcentaje in socios:
        ganancia_socio = ganancia_total_ventas * (porcentaje / 100.0)
        
        if "Principal" in nombre:
            monto_total_socio = ganancia_socio + reconocimiento_flete_socio1
            s_col1.metric(
                f"Socia: {nombre} ({porcentaje}%)", 
                f"₡{monto_total_socio:,.2f}", 
                f"Ganancia (₡{ganancia_socio:,.2f}) + Reconocimiento Flete (₡{reconocimiento_flete_socio1:,.2f})"
            )
        else:
            monto_total_socio = ganancia_socio + reconocimiento_flete_socio2
            s_col2.metric(
                f"Socio: {nombre} ({porcentaje}%)", 
                f"₡{monto_total_socio:,.2f}", 
                f"Ganancia (₡{ganancia_socio:,.2f}) + Reconocimiento Flete (₡{reconocimiento_flete_socio2:,.2f})"
            )

# --- 2. REGISTRAR COMPRA ---
elif menu == "📥 Registrar Compra":
    st.title("📥 Registrar Compra de Animal")
    st.markdown("Ingrese los datos de compra. El costo total *suma* el valor base del animal más el transporte de compra (₡10,000 por defecto).")

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
    st.markdown("Seleccione el arete, ingrese los datos de venta y el transporte de salida (flete) que se *suma* al total de salida.")
    
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

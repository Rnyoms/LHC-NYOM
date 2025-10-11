import streamlit as st
import pandas as pd
import random
import numpy as np
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import unary_union
import zipfile
import os
import tempfile
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
import datetime
import io

# ------------------ SISTEM LOGIN ------------------
AUTHORIZED_USERS = {"pbph": "pbph123"}

st.sidebar.title("🔐 Login")
with st.sidebar.form("login_form"):
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    login_btn = st.form_submit_button("Login")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if login_btn:
    if username in AUTHORIZED_USERS and password == AUTHORIZED_USERS[username]:
        st.session_state.logged_in = True
    else:
        st.sidebar.error("Login gagal. Coba lagi.")

if not st.session_state.logged_in:
    st.stop()

# ------------------ BATAS WAKTU ------------------
batas_tanggal = datetime.datetime(2025, 12, 31)
if datetime.datetime.now() > batas_tanggal:
    st.error("⚠️ Hubungi tenyoms.")
    st.stop()

# ------------------ KONSTANTA ------------------
JENIS_POHON = ["Merbau", "Kelompok Meranti", "Rimba Campuran", "Kayu Indah"]
KETENTUAN_BAKU = {
    "20-39": {"d_min": 20, "d_max": 39, "h_min": 9, "h_max": 12, "rata2_volume": 0.45},
    "40-49": {"d_min": 40, "d_max": 49, "h_min": 11, "h_max": 15, "rata2_volume": 1.38},
    "50-59": {"d_min": 50, "d_max": 59, "h_min": 12, "h_max": 17, "rata2_volume": 2.05},
    "60-99": {"d_min": 60, "d_max": 99, "h_min": 13, "h_max": 19, "rata2_volume": 3.00},
    "100UP": {"d_min": 100, "d_max": 200, "h_min": 17, "h_max": 23, "rata2_volume": 9.65}
}

# ------------------ FORM INPUT ------------------
def input_kelas_diameter(kelas_nama):
    st.subheader(f"Kelas Diameter {kelas_nama}")
    data_baku = KETENTUAN_BAKU[kelas_nama]

    col1, col2 = st.columns(2)
    with col1:
        target_volume = st.number_input(f"{kelas_nama} - Target Volume (m³)", min_value=0.0, value=5.0, step=0.1, format="%.1f", key=f"tv_{kelas_nama}")
    with col2:
        toleransi = st.number_input(f"{kelas_nama} - Toleransi Volume (m³)", min_value=0.0, value=0.1, step=0.01, format="%.2f", key=f"tol_{kelas_nama}")

    rata = data_baku.get("rata2_volume", 1.0)
    estimasi_jumlah = int(target_volume // rata) if rata > 0 else 0
    st.info(f"Perkiraan jumlah pohon: {estimasi_jumlah} pohon (rata-rata {rata} m³)")

    st.markdown(f"**Persentase Jenis Pohon - {kelas_nama}**")
    jenis_dict = {}
    for jenis in JENIS_POHON:
        persen = st.number_input(f"{kelas_nama} - {jenis} (%)", min_value=0, max_value=100, value=0, step=1, key=f"{kelas_nama}_{jenis}")
        jenis_dict[jenis] = persen

    return {
        "kelas": kelas_nama,
        "d_min": data_baku["d_min"], "d_max": data_baku["d_max"],
        "h_min": data_baku["h_min"], "h_max": data_baku["h_max"],
        "target_volume": target_volume,
        "toleransi": toleransi,
        "persen_jenis": jenis_dict
    }

def pilih_jenis(persen_jenis):
    final = {j: p for j, p in persen_jenis.items() if p > 0}
    total = sum(final.values())
    if total == 0:
        final = {j: 100/len(JENIS_POHON) for j in JENIS_POHON}
        total = sum(final.values())
    probs = [v / total for v in final.values()]
    return list(final.keys()), probs

def random_point_in_polygon(polygon, max_attempt=5000):
    """Mendapatkan titik acak dalam Polygon atau MultiPolygon. Return Point."""
    if isinstance(polygon, MultiPolygon):
        # pilih salah satu bagian secara acak (proporsional ke area bisa ditambahkan)
        polygon = random.choice(list(polygon.geoms))

    minx, miny, maxx, maxy = polygon.bounds
    for _ in range(max_attempt):
        p = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))
        if polygon.contains(p):
            return p
    # fallback ke centroid jika gagal
    return polygon.centroid

def simulasi_kelas(data_kelas, polygon):
    hasil = []
    jenis_list, probs = pilih_jenis(data_kelas["persen_jenis"])
    total_volume = 0.0
    iterasi = 0
    max_iter = 20000
    target = data_kelas["target_volume"]
    tol = data_kelas["toleransi"]

    if target <= 0:
        return hasil

    while abs(total_volume - target) > tol and iterasi < max_iter:
        diameter = random.randint(int(data_kelas["d_min"]), int(data_kelas["d_max"]))
        tinggi = random.randint(int(data_kelas["h_min"]), int(data_kelas["h_max"]))
        volume = round(0.7854 * (diameter / 100)**2 * tinggi * 0.6, 2)
        if total_volume + volume > target + tol:
            iterasi += 1
            continue
        jenis = np.random.choice(jenis_list, p=probs)
        hasil.append({
            "Kelas": data_kelas["kelas"], "Jenis": jenis,
            "Diameter_cm": diameter, "Tinggi_m": tinggi, "Volume_m3": volume
        })
        total_volume += volume
        iterasi += 1
    return hasil

def hitung_jalur_itsp(gdf_pohon_utm, min_x):
    gdf = gdf_pohon_utm.copy()
    gdf["Jalur"] = ((gdf.geometry.x - min_x) // 20).astype(int) + 1
    return gdf

# ------------------ APLIKASI ------------------
st.title("🌲 Simulasi LHC Bayangan + Jalur ITSP")

uploaded_zip = st.file_uploader("Upload Shapefile Petak (.zip)", type=["zip"])
polygon = None
if uploaded_zip:
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(uploaded_zip, "r") as zip_ref:
            zip_ref.extractall(tmpdir)

        # Cari file .shp (case-insensitive) dengan path penuh
        shp_path = None
        for root, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.lower().endswith(".shp"):
                    shp_path = os.path.join(root, f)
                    break
            if shp_path:
                break

        if shp_path:
            try:
                gdf = gpd.read_file(shp_path)
                # Pastikan CRS; jika tidak ada, anggap EPSG:4326 (harap verifikasi manual)
                if gdf.crs is None:
                    st.warning("CRS shapefile tidak ditemukan — diasumsikan EPSG:4326.")
                    gdf.set_crs(epsg=4326, inplace=True)
                else:
                    # normalisasi ke 4326 agar titik acak didapat dalam lat/lon
                    gdf = gdf.to_crs(epsg=4326)

                # gabungkan semua fitur jadi satu (Polygon atau MultiPolygon)
                geom_union = unary_union(gdf.geometry.values)
                if not isinstance(geom_union, (Polygon, MultiPolygon)):
                    st.error("Geometri shapefile bukan Polygon/MultiPolygon.")
                else:
                    polygon = geom_union
                    st.success("✅ Shapefile berhasil dimuat dan digabung.")
            except Exception as e:
                st.error(f"Gagal membaca shapefile: {e}")
        else:
            st.error("❌ File .shp tidak ditemukan dalam ZIP")

nama_petak = st.text_input("Nama Petak", "Petak-1")

# Form input kelas
kelas_20_39 = input_kelas_diameter("20-39")
kelas_40_49 = input_kelas_diameter("40-49")
kelas_50_59 = input_kelas_diameter("50-59")
kelas_60_99 = input_kelas_diameter("60-99")
kelas_100UP = input_kelas_diameter("100UP")

# ------------------ TOMBOL SIMULASI ------------------
if st.button("🚀 Jalankan Simulasi"):
    if not polygon:
        st.error("⚠️ Silakan unggah shapefile petak terlebih dahulu.")
    else:
        st.info("Simulasi sedang berjalan...")

        # 1) Simulasi berdasarkan kelas
        data_semua = []
        for kelas in [kelas_20_39, kelas_40_49, kelas_50_59, kelas_60_99, kelas_100UP]:
            data_semua.extend(simulasi_kelas(kelas, polygon))

        if len(data_semua) == 0:
            st.warning("Tidak ada data pohon yang dihasilkan. Periksa target volume/toleransi.")
            st.stop()

        # 2) Tempatkan titik acak di dalam polygon (mendukung MultiPolygon)
        random.shuffle(data_semua)
        points = [random_point_in_polygon(polygon) for _ in data_semua]
        for i, pt in enumerate(points):
            data_semua[i]["Latitude"] = pt.y
            data_semua[i]["Longitude"] = pt.x

        # 3) Buat GeoDataFrame (EPSG:4326)
        df_pohon = pd.DataFrame(data_semua)
        gdf_pohon = gpd.GeoDataFrame(df_pohon, geometry=gpd.points_from_xy(df_pohon["Longitude"], df_pohon["Latitude"]), crs="EPSG:4326")

        # 4) Konversi ke UTM zona 53S (Papua Barat)
        epsg_utm = 32753
        try:
            gdf_pohon_utm = gdf_pohon.to_crs(epsg=epsg_utm)
        except Exception as e:
            st.error(f"Gagal konversi ke EPSG:{epsg_utm} — {e}")
            st.stop()

        # 5) Konversi polygon ke UTM untuk hitung min_x
        try:
            polygon_utm = gpd.GeoSeries([polygon], crs="EPSG:4326").to_crs(epsg=epsg_utm)
            min_x = polygon_utm.bounds.minx.values[0]
        except Exception as e:
            st.warning(f"Gagal konversi polygon ke UTM: {e}. Menggunakan min x dari titik pohon.")
            min_x = gdf_pohon_utm.geometry.x.min()

        # 6) Hitung jalur ITSP (menggunakan kolom geometry UTM)
        gdf_pohon_utm = hitung_jalur_itsp(gdf_pohon_utm, min_x)

        # 7) Kembalikan ke EPSG:4326 untuk output & rekap
        try:
            gdf_final = gdf_pohon_utm.to_crs(epsg=4326)
        except Exception:
            gdf_final = gdf_pohon_utm  # jika gagal, tetap gunakan data UTM

        df_final = pd.DataFrame(gdf_final.drop(columns="geometry"))

        # 8) Rekap
        rekap = df_final.groupby(["Jenis", "Kelas"]).agg(
            Jumlah=("Jenis", "count"), Volume=("Volume_m3", "sum")
        ).reset_index()

        # 9) Simpan ke excel di memori dan tawarkan unduh (tidak menyimpan permanen)
        buffer = io.BytesIO()
        wb = Workbook()
        ws_data = wb.active
        ws_data.title = "DataPohon"
        for r in dataframe_to_rows(df_final, index=False, header=True):
            ws_data.append(r)

        ws_rekap = wb.create_sheet("Rekap")
        for r in dataframe_to_rows(rekap, index=False, header=True):
            ws_rekap.append(r)

        wb.save(buffer)
        buffer.seek(0)

        st.success("Hasil simulasi siap diunduh.")
        st.dataframe(rekap)
        st.download_button("⬇️ Unduh Excel", data=buffer, file_name=f"{nama_petak}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

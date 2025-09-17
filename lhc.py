import streamlit as st
import pandas as pd
import random
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
import zipfile
import os
import tempfile
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
import datetime

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
batas_tanggal = datetime.datetime(2025, 11, 16)
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
        target_volume = st.number_input(f"{kelas_nama} - Target Volume (m³)", min_value=0.0, value=5.0, step=0.1, format="%.1f")
    with col2:
        toleransi = st.number_input(f"{kelas_nama} - Toleransi Volume (m³)", min_value=0.0, value=0.1, step=0.01, format="%.2f")

    estimasi_jumlah = int(target_volume // data_baku["rata2_volume"])
    st.info(f"Perkiraan jumlah pohon: {estimasi_jumlah} pohon (rata-rata {data_baku['rata2_volume']} m³)")

    st.markdown(f"**Persentase Jenis Pohon - {kelas_nama}**")
    jenis_dict = {}
    for jenis in JENIS_POHON:
        persen = st.number_input(f"{jenis} (%)", min_value=0, max_value=100, value=0, step=1, key=f"{kelas_nama}_{jenis}")
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
        final = {j: 25 for j in JENIS_POHON}
        total = 100
    probs = [v / total for v in final.values()]
    return list(final.keys()), probs

def random_point_in_polygon(polygon):
    minx, miny, maxx, maxy = polygon.bounds
    while True:
        p = Point(random.uniform(minx, maxx), random.uniform(miny, maxy))
        if polygon.contains(p):
            return p

def simulasi_kelas(data_kelas, polygon):
    hasil = []
    jenis_list, probs = pilih_jenis(data_kelas["persen_jenis"])
    total_volume = 0
    iterasi = 0
    max_iter = 100000
    while abs(total_volume - data_kelas["target_volume"]) > data_kelas["toleransi"] and iterasi < max_iter:
        diameter = random.randint(int(data_kelas["d_min"]), int(data_kelas["d_max"]))
        tinggi = random.randint(int(data_kelas["h_min"]), int(data_kelas["h_max"]))
        volume = round(0.7854 * (diameter / 100)**2 * tinggi * 0.6, 2)
        if total_volume + volume > data_kelas["target_volume"] + data_kelas["toleransi"]:
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
    gdf_pohon_utm["Jalur"] = ((gdf_pohon_utm.geometry.x - min_x) // 20).astype(int) + 1
    return gdf_pohon_utm

# ------------------ APLIKASI ------------------
st.title("🌲 Simulasi LHC Bayangan + Jalur ITSP")

uploaded_zip = st.file_uploader("Upload Shapefile Petak (.zip)", type=["zip"])
polygon = None
if uploaded_zip:
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(uploaded_zip, "r") as zip_ref:
            zip_ref.extractall(tmpdir)
        shp_files = [f for f in os.listdir(tmpdir) if f.endswith(".shp")]
        if shp_files:
            gdf = gpd.read_file(os.path.join(tmpdir, shp_files[0]))
            gdf = gdf.to_crs(epsg=4326)
            polygon = gdf.geometry.iloc[0]
            st.success("✅ Shapefile berhasil dimuat")

nama_petak = st.text_input("Nama Petak", "Petak-1")

# Form input kelas
kelas_20_39 = input_kelas_diameter("20-39")
kelas_40_49 = input_kelas_diameter("40-49")
kelas_50_59 = input_kelas_diameter("50-59")
kelas_60_99 = input_kelas_diameter("60-99")
kelas_100UP = input_kelas_diameter("100UP")

# Tombol simulasi
if st.button("🚀 Jalankan Simulasi"):
    if not polygon:
        st.error("⚠️ Silakan unggah shapefile petak terlebih dahulu.")
    else:
        st.info("Simulasi sedang berjalan...")

        data_semua = []
        for kelas in [kelas_20_39, kelas_40_49, kelas_50_59, kelas_60_99, kelas_100UP]:
            data_semua.extend(simulasi_kelas(kelas, polygon))

        random.shuffle(data_semua)
        list_point = [random_point_in_polygon(polygon) for _ in data_semua]
        for i, pt in enumerate(list_point):
            data_semua[i]["Latitude"] = pt.y
            data_semua[i]["Longitude"] = pt.x

        df_pohon = pd.DataFrame(data_semua)
        gdf_pohon = gpd.GeoDataFrame(df_pohon, geometry=gpd.points_from_xy(df_pohon["Longitude"], df_pohon["Latitude"]), crs="EPSG:4326")
        gdf_pohon_utm = gdf_pohon.to_crs(epsg=32753)
        polygon_utm = gpd.GeoSeries([polygon], crs="EPSG:4326").to_crs(epsg=32753)
        min_x = polygon_utm.bounds.minx.values[0]
        gdf_pohon_utm = hitung_jalur_itsp(gdf_pohon_utm, min_x)

        gdf_final = gdf_pohon_utm.to_crs(epsg=4326)
        df_final = pd.DataFrame(gdf_final.drop(columns="geometry"))

        rekap = df_final.groupby(["Jenis", "Kelas"]).agg(
            Jumlah=("Jenis", "count"), Volume=("Volume_m3", "sum")
        ).reset_index()

        wb = Workbook()
        ws_data = wb.active
        ws_data.title = "DataPohon"
        for r in dataframe_to_rows(df_final, index=False, header=True):
            ws_data.append(r)

        ws_rekap = wb.create_sheet("Rekap")
        for r in dataframe_to_rows(rekap, index=False, header=True):
            ws_rekap.append(r)

        filename = f"{nama_petak}.xlsx"
        wb.save(filename)

        st.success(f"Hasil simulasi berhasil disimpan sebagai: {filename}")
        st.download_button("⬇️ Unduh Excel", open(filename, "rb"), file_name=filename)


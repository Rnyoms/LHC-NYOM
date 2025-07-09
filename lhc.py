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

# ------------------ SISTEM LOGIN DENGAN TOMBOL ------------------
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
batas_tanggal = datetime.datetime(2025, 7, 16)
if datetime.datetime.now() > batas_tanggal:
    st.error("⚠️ Akses aplikasi ini telah ditutup sejak 16 Juli 2025.")
    st.stop()

# ------------------ APLIKASI ------------------

JENIS_POHON = ["Merbau", "Kelompok Meranti", "Rimba Campuran", "Kayu Indah"]

RATA2_VOLUME = {
    "40-49": 1.12,
    "50-59": 2.34,
    "60-90": 6.5,
    "100UP": 10.0
}

def input_kelas_diameter(kelas_nama):
    st.subheader(f"Kelas Diameter {kelas_nama}")
    col1, col2 = st.columns(2)

    with col1:
        d_min = st.number_input(f"{kelas_nama} - Diameter Min (cm)", min_value=10, value=40, step=1, format="%d")
        h_min = st.number_input(f"{kelas_nama} - Tinggi Min (m)", min_value=5, value=10, step=1, format="%d")
        target_volume = st.number_input(f"{kelas_nama} - Target Volume (m³)", min_value=0.0, value=5.0, step=0.1, format="%.1f")

    with col2:
        d_max = st.number_input(f"{kelas_nama} - Diameter Max (cm)", min_value=10, value=49, step=1, format="%d")
        h_max = st.number_input(f"{kelas_nama} - Tinggi Max (m)", min_value=5, value=30, step=1, format="%d")
        toleransi = st.number_input(f"{kelas_nama} - Toleransi Volume (m³)", min_value=0.0, value=0.1, step=0.01, format="%.2f")

    rata2 = RATA2_VOLUME[kelas_nama]
    estimasi_jumlah = int(target_volume // rata2)
    st.info(f"Perkiraan jumlah pohon: {estimasi_jumlah} pohon (dengan rata-rata {rata2} m³)")

    st.markdown(f"**Persentase Jenis Pohon - {kelas_nama}**")
    jenis_dict = {}
    for jenis in JENIS_POHON:
        persen = st.number_input(f"{jenis} (%)", min_value=0, max_value=100, value=0, step=1, format="%d", key=f"{kelas_nama}_{jenis}")
        jenis_dict[jenis] = persen

    return {
        "kelas": kelas_nama,
        "d_min": d_min, "d_max": d_max,
        "h_min": h_min, "h_max": h_max,
        "target_volume": target_volume,
        "toleransi": toleransi,
        "persen_jenis": jenis_dict
    }

def pilih_jenis(persen_jenis):
    eksplisit = {j: p for j, p in persen_jenis.items() if p > 0}
    kosong = [j for j, p in persen_jenis.items() if p == 0]
    total_eksplisit = sum(eksplisit.values())
    sisa = max(0, 100 - total_eksplisit)
    rata = sisa / len(kosong) if kosong else 0
    final = eksplisit.copy()
    for j in kosong:
        final[j] = rata
    total = sum(final.values())
    probs = [final[j]/total for j in final]
    return list(final.keys()), probs

def random_point_in_polygon(polygon):
    minx, miny, maxx, maxy = polygon.bounds
    while True:
        x = random.uniform(minx, maxx)
        y = random.uniform(miny, maxy)
        p = Point(x, y)
        if polygon.contains(p):
            return p

def simulasi_kelas(data_kelas, polygon):
    hasil = []
    jenis_list, probs = pilih_jenis(data_kelas["persen_jenis"])
    total_volume = 0
    iterasi = 0
    max_iter = 100000
    target = data_kelas["target_volume"]
    toleransi = data_kelas["toleransi"]

    while abs(total_volume - target) > toleransi and iterasi < max_iter:
        diameter = random.randint(int(data_kelas["d_min"]), int(data_kelas["d_max"]))
        tinggi = random.randint(int(data_kelas["h_min"]), int(data_kelas["h_max"]))
        volume = round(0.7854 * (diameter / 100)**2 * tinggi * 0.6, 2)

        if total_volume + volume > target + toleransi:
            iterasi += 1
            continue

        jenis = np.random.choice(jenis_list, p=probs)
        point = random_point_in_polygon(polygon)
        hasil.append({
            "Kelas": data_kelas["kelas"],
            "Jenis": jenis,
            "Diameter_cm": diameter,
            "Tinggi_m": tinggi,
            "Volume_m3": volume,
            "Latitude": point.y,
            "Longitude": point.x
        })
        total_volume += volume
        iterasi += 1

    return hasil

def export_to_excel(nama_petak, data_pohon):
    df = pd.DataFrame(data_pohon)
    rekap = df.groupby(["Jenis", "Kelas"]).agg(
        Jumlah=("Jenis", "count"),
        Volume=("Volume_m3", "sum")
    ).reset_index()

    wb = Workbook()
    ws_data = wb.active
    ws_data.title = "DataPohon"
    for r in dataframe_to_rows(df, index=False, header=True):
        ws_data.append(r)

    ws_rekap = wb.create_sheet("Rekap")
    for r in dataframe_to_rows(rekap, index=False, header=True):
        ws_rekap.append(r)

    filename = f"{nama_petak}.xlsx"
    wb.save(filename)
    return filename

st.title("Simulasi LHC Bayangan - Dengan Koordinat di Dalam Petak")

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
            st.success("Shapefile petak berhasil dimuat.")

nama_petak = st.text_input("Nama Petak", "Petak-1")
kelas_40_49 = input_kelas_diameter("40-49")
kelas_50_59 = input_kelas_diameter("50-59")
kelas_60_90 = input_kelas_diameter("60-90")
kelas_100UP = input_kelas_diameter("100UP")

if st.button("Lanjutkan Simulasi"):
    if not polygon:
        st.error("Silakan unggah shapefile petak terlebih dahulu.")
    else:
        st.success(f"Simulasi sedang diproses untuk petak: {nama_petak}")

        data_semua = []
        for kelas_data in [kelas_40_49, kelas_50_59, kelas_60_90, kelas_100UP]:
            data_semua += simulasi_kelas(kelas_data, polygon)

        filename = export_to_excel(nama_petak, data_semua)
        st.success(f"Hasil simulasi berhasil disimpan: {filename}")
        st.download_button("Unduh Excel", open(filename, "rb"), file_name=filename)

import cv2
import numpy as np
import psycopg2
import streamlit as st
from PIL import Image
from psycopg2.extras import RealDictCursor

DUNKIN_PINK = "#E11383"
DUNKIN_ORANGE = "#F5821F"
DUNKIN_BROWN = "#683817"
DUNKIN_WHITE = "#FCF6F6"

st.set_page_config(page_title="Dunkin' Offers | Scanner", page_icon="🍩")

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fredoka+One&family=Open+Sans:wght@400;700&display=swap');

    .main {{
        background-color: {DUNKIN_WHITE};
    }}
    h1, h2, h3 {{
        font-family: 'Fredoka One', cursive;
        color: {DUNKIN_PINK};
    }}
    p, span {{
        font-family: 'Open Sans', sans-serif;
        color: {DUNKIN_BROWN};
    }}
    .stButton>button {{
        background-color: {DUNKIN_ORANGE};
        color: white;
        border-radius: 50px;
        border: none;
        font-weight: bold;
        padding: 10px 25px;
        border: 2px solid {DUNKIN_ORANGE};
    }}
    .stButton>button:hover {{
        background-color: white;
        color: {DUNKIN_ORANGE};
        border: 2px solid {DUNKIN_ORANGE};
    }}
    .offer-card {{
        background-color: white;
        padding: 25px;
        border-radius: 20px;
        border: 4px solid {DUNKIN_PINK};
        text-align: center;
        box-shadow: 10px 10px 0px {DUNKIN_ORANGE};
    }}
    .price-tag-original {{
        text-decoration: line-through;
        color: #999;
        font-size: 1.1rem;
    }}
    .price-tag-final {{
        color: {DUNKIN_PINK};
        font-size: 2.5rem;
        font-weight: bold;
        margin: 5px 0;
    }}
    .coupon-info {{
        background-color: {DUNKIN_BROWN};
        color: white;
        padding: 5px 15px;
        border-radius: 10px;
        font-size: 0.8rem;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def get_connection():
    neon_config = st.secrets["neon"]
    database_url = neon_config.get("url")

    if database_url:
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=neon_config["host"],
        database=neon_config["database"],
        user=neon_config["user"],
        password=neon_config["password"],
        sslmode="require",
    )


def get_offer_data(coupon_id):
    """
    Busca os dados do cupom e do produto no schema mostrado pelos JSONs.
    """
    conn = None
    try:
        coupon_id = int(str(coupon_id).strip())
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = """
                SELECT
                    p.name,
                    p.description,
                    p.category,
                    p.unit,
                    p.price,
                    p.image,
                    c.id AS coupon_id,
                    c.discount_percent
                FROM coupons c
                JOIN products p ON c.product_id = p.id
                WHERE c.id = %s
                  AND c.active = TRUE
                  AND p.active = TRUE;
            """
            cur.execute(query, (coupon_id,))
            return cur.fetchone()
    except ValueError:
        st.error("O QR Code precisa conter um ID numerico de cupom.")
        return None
    except Exception as exc:
        st.error(f"Erro ao conectar com o banco: {exc}")
        return None
    finally:
        if conn is not None:
            conn.close()


def process_qr_code(image):
    img_array = np.array(image.convert("RGB"))
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img_array)
    return data.strip() if data else None


st.image(
    "https://upload.wikimedia.org/wikipedia/en/thumb/d/d3/Dunkin_Donuts_logo.svg/1200px-Dunkin_Donuts_logo.svg.png",
    width=180,
)
st.title("Ofertas Deliciosas!")
st.write("Escaneie seu cupom para ver o desconto exclusivo.")

col1, col2 = st.columns(2)

with col1:
    cam_input = st.camera_input("Scanner de Cupom")

with col2:
    uploaded_img = st.file_uploader(
        "Ou envie a foto do QR Code", type=["png", "jpg", "jpeg"]
    )

coupon_id = None
if cam_input:
    coupon_id = process_qr_code(Image.open(cam_input))
elif uploaded_img:
    coupon_id = process_qr_code(Image.open(uploaded_img))

if coupon_id:
    data = get_offer_data(coupon_id)

    if data:
        price = float(data["price"])
        discount_percent = float(data["discount_percent"])
        discount_amount = price * (discount_percent / 100)
        final_price = price - discount_amount

        st.markdown(
            f"""
            <div class="offer-card">
                <span class="coupon-info">CUPOM ATIVO: {data["coupon_id"]} | {discount_percent:.0f}% OFF</span>
                <h2 style="margin: 15px 0;">{data["name"]}</h2>
                <p style="margin-bottom: 10px;">{data["description"]}</p>
                <p class="price-tag-original">Preco normal: R$ {price:,.2f}</p>
                <p style="margin:0; font-weight:bold; color:{DUNKIN_ORANGE};">COM SEU DESCONTO:</p>
                <p class="price-tag-final">R$ {final_price:,.2f}</p>
                <p style="color: {DUNKIN_BROWN}; font-size: 0.9rem;">Voce economiza R$ {discount_amount:,.2f} nesta oferta!</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.button(f"QUERO MEU {data['name'].upper()}! 🍩")
    else:
        st.error("Esse cupom nao foi encontrado, esta inativo ou o produto esta indisponivel.")
else:
    if cam_input or uploaded_img:
        st.warning("Nao conseguimos ler o QR Code. Tente aproximar mais da camera.")

st.markdown("---")
st.caption("Dunkin' App | Conectado ao PostgreSQL via Neon.tech")

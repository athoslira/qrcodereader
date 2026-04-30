import queue

import av
import cv2
import numpy as np
import psycopg2
import streamlit as st
from PIL import Image
from psycopg2.extras import RealDictCursor

WEBRTC_AVAILABLE = True
WEBRTC_IMPORT_ERROR = None

try:
    from streamlit_webrtc import RTCConfiguration, WebRtcMode, webrtc_streamer
except Exception as exc:
    WEBRTC_AVAILABLE = False
    WEBRTC_IMPORT_ERROR = exc

FRAGMENT_DECORATOR = getattr(st, "fragment", getattr(st, "experimental_fragment", None))

DUNKIN_PINK = "#E11383"
DUNKIN_ORANGE = "#F5821F"
DUNKIN_BROWN = "#683817"
DUNKIN_WHITE = "#FCF6F6"

RTC_CONFIGURATION = (
    RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})
    if WEBRTC_AVAILABLE
    else None
)

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


class LiveQRProcessor:
    def __init__(self):
        self.detector = cv2.QRCodeDetector()
        self.result_queue = queue.Queue()
        self.last_sent_code = None

    def recv(self, frame):
        image = frame.to_ndarray(format="bgr24")
        code, points = self._read_code(image)

        if points is not None:
            pts = points.astype(int).reshape((-1, 1, 2))
            cv2.polylines(image, [pts], True, (0, 200, 0), 3)

        if code:
            cv2.putText(
                image,
                f"Cupom: {code}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 200, 0),
                2,
                cv2.LINE_AA,
            )
            if code != self.last_sent_code:
                self.result_queue.put(code)
                self.last_sent_code = code

        return av.VideoFrame.from_ndarray(image, format="bgr24")

    def _read_code(self, image):
        try:
            found, decoded_info, points, _ = self.detector.detectAndDecodeMulti(image)
            if found and decoded_info:
                for index, value in enumerate(decoded_info):
                    code = value.strip()
                    if code:
                        selected_points = points[index] if points is not None else None
                        return code, selected_points
        except Exception:
            pass

        code, points, _ = self.detector.detectAndDecode(image)
        clean_code = code.strip() if code else None
        return clean_code, points


def get_connection():
    if "neon" not in st.secrets:
        raise RuntimeError(
            "Secrets do Neon nao encontrados. Configure a secao [neon] nos Secrets do Streamlit Cloud."
        )

    neon_config = st.secrets["neon"]
    database_url = neon_config.get("url")

    if database_url:
        return psycopg2.connect(database_url, connect_timeout=10)

    return psycopg2.connect(
        host=neon_config["host"],
        database=neon_config["database"],
        user=neon_config["user"],
        password=neon_config["password"],
        sslmode="require",
        connect_timeout=10,
    )


def get_offer_data(coupon_id):
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
        st.session_state["scan_error"] = "O QR Code precisa conter um ID numerico de cupom."
        return None
    except Exception as exc:
        st.session_state["scan_error"] = f"Erro ao conectar com o banco: {exc}"
        return None
    finally:
        if conn is not None:
            conn.close()


def process_qr_code(image):
    img_array = np.array(image.convert("RGB"))
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img_array)
    return data.strip() if data else None


def handle_coupon_lookup(coupon_id):
    st.session_state["last_coupon_id"] = str(coupon_id).strip()
    st.session_state["offer_data"] = get_offer_data(coupon_id)
    if st.session_state["offer_data"] is None and "scan_error" not in st.session_state:
        st.session_state["scan_error"] = (
            "Esse cupom nao foi encontrado, esta inativo ou o produto esta indisponivel."
        )
    elif st.session_state["offer_data"] is not None:
        st.session_state.pop("scan_error", None)


def render_offer(data):
    price = float(data["price"])
    discount_percent = float(data["discount_percent"])
    discount_amount = price * (discount_percent / 100)
    final_price = price - discount_amount

    if data.get("image"):
        st.image(data["image"], width=240)

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


def render_live_scanner():
    st.write("Clique em START e aponte a camera para o QR Code.")
    st.caption("A leitura acontece continuamente enquanto a transmissao estiver ativa.")

    webrtc_ctx = webrtc_streamer(
        key="qr-live-reader",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=RTC_CONFIGURATION,
        media_stream_constraints={"video": {"facingMode": "environment"}, "audio": False},
        video_processor_factory=LiveQRProcessor,
        async_processing=True,
    )

    if not webrtc_ctx.state.playing:
        st.caption("A leitura ao vivo comecara quando voce clicar em START.")
        return

    st.info("Lendo QR Code em tempo real...")

    if not webrtc_ctx.video_processor:
        return

    latest_code = None
    while True:
        try:
            latest_code = webrtc_ctx.video_processor.result_queue.get_nowait()
        except queue.Empty:
            break

    if latest_code and latest_code != st.session_state.get("last_coupon_id"):
        handle_coupon_lookup(latest_code)
        st.rerun()


if WEBRTC_AVAILABLE and FRAGMENT_DECORATOR is not None:
    render_live_scanner = FRAGMENT_DECORATOR(run_every=0.5)(render_live_scanner)


if "offer_data" not in st.session_state:
    st.session_state["offer_data"] = None
if "last_coupon_id" not in st.session_state:
    st.session_state["last_coupon_id"] = None

st.image(
    "https://upload.wikimedia.org/wikipedia/en/thumb/d/d3/Dunkin_Donuts_logo.svg/1200px-Dunkin_Donuts_logo.svg.png",
    width=180,
)
st.title("Ofertas Deliciosas!")
st.write("Escaneie seu cupom para ver o desconto exclusivo.")

if WEBRTC_AVAILABLE:
    tab_live, tab_upload = st.tabs(["Leitura ao vivo", "Enviar imagem"])
else:
    tab_upload = st.container()
    st.warning(
        "A leitura ao vivo nao esta disponivel neste deploy. O app continuara funcionando com envio de imagem."
    )
    st.caption(f"Detalhe tecnico do ambiente: {type(WEBRTC_IMPORT_ERROR).__name__}")

if WEBRTC_AVAILABLE:
    with tab_live:
        if FRAGMENT_DECORATOR is not None:
            render_live_scanner()
        else:
            st.warning(
                "Leitura ao vivo limitada nesta versao do Streamlit. Atualize o Streamlit para uma versao com suporte a fragments para mais estabilidade."
            )
            render_live_scanner()

with tab_upload:
    uploaded_img = st.file_uploader(
        "Ou envie a foto do QR Code", type=["png", "jpg", "jpeg"]
    )
    if uploaded_img:
        coupon_id = process_qr_code(Image.open(uploaded_img))
        if coupon_id:
            handle_coupon_lookup(coupon_id)
        else:
            st.session_state["offer_data"] = None
            st.session_state["scan_error"] = (
                "Nao conseguimos ler o QR Code. Tente uma imagem mais nitida."
            )

if st.session_state.get("offer_data"):
    render_offer(st.session_state["offer_data"])
elif st.session_state.get("scan_error"):
    st.error(st.session_state["scan_error"])

st.markdown("---")
st.caption("Dunkin' App | Conectado ao PostgreSQL via Neon.tech")

"""Static fallback ticker universe for BIST watchlists.

BIST 100 endeksi referans listesi (2024-2025 donemi). Endeks periyodik olarak
guncellenir; surekli takip icin BorsaIstanbulQuoteProvider veya official provider
kullanilmasi onerilir. Bu liste sadece veri saglayicidan canli tickerlar
cekilemediginde fallback amacli kullanilir.

Liste tekrarsizdir ve gercek BIST tickerlarini icerir. Bilinmeyen veya delist
edilen tickerlar dahil edilmemistir.
"""

BIST100_TICKERS = [
    # Bankacilik & Finans (10)
    "AKBNK.IS",
    "GARAN.IS",
    "HALKB.IS",
    "ISCTR.IS",
    "VAKBN.IS",
    "YKBNK.IS",
    "ALBRK.IS",
    "QNBFB.IS",
    "SKBNK.IS",
    "TSKB.IS",
    # Holding (8)
    "KCHOL.IS",
    "SAHOL.IS",
    "DOHOL.IS",
    "GLYHO.IS",
    "GSDHO.IS",
    "ALARK.IS",
    "ECILC.IS",
    "YGGYO.IS",
    # Havayolu & Ulastirma (5)
    "THYAO.IS",
    "PGSUS.IS",
    "TAVHL.IS",
    "CLEBI.IS",
    "DOCO.IS",
    # Otomotiv (6)
    "FROTO.IS",
    "TOASO.IS",
    "TTRAK.IS",
    "OTKAR.IS",
    "DOAS.IS",
    "KARSN.IS",
    # Demir-Celik & Metal (5)
    "EREGL.IS",
    "KRDMD.IS",
    "BRSAN.IS",
    "CEMTS.IS",
    "IZMDC.IS",
    # Kimya & Petrokimya & Rafineri (8)
    "TUPRS.IS",
    "PETKM.IS",
    "SASA.IS",
    "AKSA.IS",
    "ALKIM.IS",
    "GUBRF.IS",
    "BAGFS.IS",
    "HEKTS.IS",
    # Cimento & Insaat (6)
    "CIMSA.IS",
    "AKCNS.IS",
    "OYAKC.IS",
    "BTCIM.IS",
    "ENKAI.IS",
    "TKFEN.IS",
    # Cam (2)
    "SISE.IS",
    "ANACM.IS",
    # Beyaz Esya & Dayanikli Tuketim (3)
    "ARCLK.IS",
    "VESTL.IS",
    "VESBE.IS",
    # Gida & Icecek & Perakende (8)
    "BIMAS.IS",
    "MGROS.IS",
    "SOKM.IS",
    "AEFES.IS",
    "CCOLA.IS",
    "ULKER.IS",
    "TUKAS.IS",
    "PNSUT.IS",
    # Enerji & Elektrik (9)
    "ENJSA.IS",
    "AKSEN.IS",
    "AYGAZ.IS",
    "ZOREN.IS",
    "ODAS.IS",
    "AYDEM.IS",
    "CWENE.IS",
    "SMRTG.IS",
    "EUPWR.IS",
    # Teknoloji & Savunma (11)
    "ASELS.IS",
    "LOGO.IS",
    "KAREL.IS",
    "NETAS.IS",
    "INDES.IS",
    "ARENA.IS",
    "FONET.IS",
    "MIATK.IS",
    "KONTR.IS",
    "GESAN.IS",
    "PAPIL.IS",
    # Iletisim (2)
    "TCELL.IS",
    "TTKOM.IS",
    # Madencilik (3)
    "KOZAL.IS",
    "KOZAA.IS",
    "IPEKE.IS",
    # Lastik (1)
    "BRISA.IS",
    # Tekstil & Hazir Giyim (2)
    "MAVI.IS",
    "DESA.IS",
    # Ilac & Saglik (4)
    "DEVA.IS",
    "LKMNH.IS",
    "MPARK.IS",
    "SELEC.IS",
    # Gayrimenkul (4)
    "EKGYO.IS",
    "ISGYO.IS",
    "AKMGY.IS",
    "TRGYO.IS",
    # Spor & Diger Sanayi (3)
    "FENER.IS",
    "BJKAS.IS",
    "GSRAY.IS",
]

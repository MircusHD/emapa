
eMapa Apa Prod - doc-mapa v2

Structura:
- app.py (aplicatia Streamlit principala)
- services/ (notificari, audit, backup)
- api/ (API REST optional)
- data/ (uploads, signatures, final pdf, baza de date)
- backup/ (copii automate DB)

Pornire aplicatie:

    streamlit run app.py --server.address 192.168.5.111 --server.port 2645

Recomandat server Windows cu NSSM sau serviciu systemd pe Linux.

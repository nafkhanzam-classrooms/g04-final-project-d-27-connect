[![Review Assignment Due Date](https://classroom.github.com/assets/deadline-readme-button-22041afd0340ce965d47ae6ef1cefeee28c7c493a6346c4f15d667ab976d596c.svg)](https://classroom.github.com/a/l3GuW2ST)
# Network Programming - Aplikasi Multi-Chat Rooms (StealthNet)

## Anggota Kelompok
| Nama                   | NRP        | Kelas |
| ---                    | ---        | ---   |
| Farikh Muhammad Fauzan     | 5025241135| D|


## Tautan Video YouTube Demo (*Unlisted*)
```text
https://youtu.be/JVfrw4PqOns
```

---

## Penjelasan Program
**StealthNet** adalah sistem aplikasi *client-server* Multi-Chat Rooms yang diimplementasikan menggunakan kombinasi protokol **TCP Socket** murni dan **WebSocket** untuk menunjang komunikasi antarmuka web secara *real-time*. Sistem ini dibangun untuk memenuhi kriteria aplikasi multi-chat, menangani multi-klien tanpa saling memblokir, serta menyediakan sinkronisasi data yang persisten.

Arsitektur program dibagi menjadi tiga komponen jaringan yang saling berinteraksi:

### 1. TCP Server Utama (`server.py` & `room_manager.py`)
Bertindak sebagai "jantung" jaringan. Server ini dibangun menggunakan **Raw TCP Sockets** (`socket.socket`) di Python tanpa bantuan framework web *high-level*.
- **I/O Multiplexing dengan `select`:** Untuk melayani banyak klien secara bersamaan (*concurrent*), server memanfaatkan modul `select.select()`. Teknik ini mencegah pemblokiran koneksi tunggal, memungkinkan server secara asinkron mendengarkan lalu lintas puluhan klien dalam satu *thread* (utas) loop utama.
- **Protokol Framing (Prefix-Length):** Mengingat sifat TCP sebagai aliran *stream* tanpa batas bawaan, setiap pesan JSON tidak dikirim secara mentah, melainkan dibungkus menggunakan protokol khusus `[4-byte Length Header] + [Payload JSON]`. Header dipaketkan via `struct.pack('!I', length)` untuk menghindari *TCP Stream Fragmentation* (menghindari pesan terpotong atau saling menempel).
- **Manajemen State (`room_manager.py`):** Modul ini mengabstraksi penyimpanan Database SQLite. Server secara persisten menarik riwayat obrolan, mengelola kamar (`rooms`), melakukan Autentikasi sandi, serta mendaftar list teman (Add/Accept Friend).

### 2. WebSocket Proxy (`ws_proxy.py`)
Bertindak sebagai *bridge* dari *browser* ke *server* TCP. Karena keamanan *browser* modern tidak mengizinkan koneksi langsung ke antarmuka raw TCP, aplikasi menggunakan penengah ini.
- Menangkap koneksi WebSocket *inbound* dari klien (menggunakan *library* `websockets` & `asyncio`).
- Membuka sambungan pipa (*pipe*) *backend* ke TCP server port `5000`.
- Memanipulasi paket di perjalanan: Mengemas teks *browser* menjadi format *Header TCP 4-byte* sebelum dikirimkan ke server utama, dan memecah struktur TCP Header dari balasan server untuk diteruskan murni sebagai teks JSON ke *browser*.

### 3. Frontend Klien Web (`client/web/chat.html`)
Antarmuka pengguna direkayasa dengan pendekatan *Vanilla JavaScript* dan HTML5, tetapi berperilaku sangat reaktif layaknya Single Page Application (SPA).
- Mengelola sambungan persisten melalui `new WebSocket()`.
- **Event-Driven UI:** Frontend mencerna *event* masuk seperti `ONLINE_STATUS` atau `ROOM_HISTORY` dan merender ulang sebagian mikro-elemen DOM spesifik (seperti daftar teman dan jumlah *online members*) secara presisi tanpa memuat ulang laman (*refresh-less*).
- **Blob & Base64:** Fitur bonus transfer file gambar, PDF, serta pesan suara di-enkode pada *client-side* ke *Base64* (berbatasan maksimal 10MB) dan dimasukkan pada muatan (payload) JSON agar mudah melintasi transmisi soket sebelum didekode oleh peramban penerima. Fitur rahasia E2EE (*End-to-End Encryption*) juga dieksekusi secara kriptografi asimetris di bagian ini.

## Alur Singkat Koneksi Jaringan
1. User memasukkan kredensial dan menekan tombol *Login*. Browser mengirim objek JSON `{"type": "LOGIN"}` via WebSocket.
2. Proxy menerjemahkannya dengan menempelkan `4-byte` header dan mendorongnya ke raw TCP Socket Server.
3. TCP Server memvalidasi hash ke dalam SQLite. Jika sesuai, TCP mengirimkan `{"type": "LOGIN_SUCCESS"}` beserta struktur data awalan `INITIAL_DATA` berisikan teman dan status ke Proxy.
4. Proxy melepaskan paket 4-byte dan mengirim JSON utuh ke browser klien via TCP Websocket Protocol.
5. Antarmuka UI seketika membangun elemen daftar ruang (*workspaces*), *online members*, dan memuat obrolan (History) sebelumnya secara *asynchronous*.

---

## Fitur-Fitur 

### Ketentuan Wajib:
* **Autentikasi:** Login / Registrasi untuk multi-client.
* **TCP & Multiplexing:** `socket` murni menggunakan `select`.
* **Serialization:** Protokol pertukaran JSON yang ketat.
* **Banyak Ruangan (Multi-Rooms):** Mampu Join, Create, dan Kicking anggota dengan *invite code*.
* **Broadcast Message:** Distribusi real-time *chat* dalam satu *workspace*.
* **Private Message (PM):** Komunikasi tertutup antar kontak (Friends).
* **Online User List:** Indikator titik hijau untuk member aktif, otomatis abu-abu jika offline.
* **Timestamp & History:** Waktu lokal per zona pengirim & Load percakapan lampau.
* **Server Logging:** Tersedia *console logging* via kontainer daemon.

### Fitur Bonus (Telah Diimplementasikan)

* **File Transfer:** Mendukung pengiriman gambar, video, dan dokumen/PDF (Maks. 10MB/pesan).
* **Voice Chat:** Perekam mikrofon *in-app* dengan pemutar (*playback*) terintegrasi.
* **Emoji Picker:** Fitur pilihan emotikon bawaan.
* **Database Persistence:** Penyimpanan data riwayat aman di SQLite (`stealthnet.db`).
* **Role Admin System:** Pembagian hak otonomi ruang obrolan. Admin memiliki akses khusus untuk *Promote* atau *Kick* member.
* **Keamanan Kriptografi (AES-GCM):**
   - **Protokol:** Menggunakan standar *Web Crypto API*.
  - **Key Derivation:** Menggunakan algoritma **PBKDF2** untuk membangkitkan kunci enkripsi simetris tingkat tinggi.
  - **Pengacakan (IV):** Menggunakan *Initialization Vector* 12-byte acak per pesan, dikonversi ke format *Base64*.
  - **Zero-Knowledge Server:** Pesan dienkripsi penuh di sisi klien (*browser*). Server hanya meneruskan *ciphertext* dan tidak akan pernah tahu isi pesan maupun kunci aslinya (E2EE).


---

## Cara Menjalankan Aplikasi
Lingkungan telah dipak menggunakan *Docker* untuk memastikan semua program dieksekusi secara mulus pada lingkungan apapun.

1. Buka Terminal pada direktori root repositori ini.
2. Ubah akses eksekusi script startup:
   ```bash
   chmod +x start_all.sh
   ```
3. Jalankan startup script:
   ```bash
   ./start_all.sh
   ```
4. Buka Browser dan kunjungi alamat UI web:
   ```text
   http://localhost:80
   ```
5. Pantau *Live Log* TCP Server pada terminal terpisah:
   ```bash
   docker-compose logs -f tcp-backend
   ```
6. Hentikan eksekusi secara penuh:
   ```bash
   docker-compose down
   ```

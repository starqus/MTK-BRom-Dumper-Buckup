# MediaTek BROM Dumper & Forensic Extractor (AutoDumper MTK)

A fully automated, low-level Python tool designed for hardware-level acquisition (BROM mode) and automated digital forensic extraction from **MediaTek (MTK)** devices.

---

## 🚀 Features

1. **Hardware-Level BROM Handshake (`0xA0 0x0A 0x50 0x05`):**
   * Automatically monitors COM ports and catches the short preloader/BROM connection window (< 3 seconds).
   * Synchronizes with MediaTek Boot ROM before the operating system boots.

2. **Watchdog Timer (WDT) Killer:**
   * Sends hardware register writes directly to the MTK Power Management / Watchdog controller (`0x10007000`) via BROM `CMD_WRITE32`.
   * Prevents PMIC 32-second shutdown timeouts, keeping the motherboard powered continuously over USB.

3. **Download Agent (DA) & DRAM (EMI) Initialization:**
   * Reads NAND/eMMC CID and configures DRAM timing via DA1 / DA2 stage loaders.
   * Dumps 100% of physical storage (eMMC User Area) in chunked 8MB blocks with unbuffered stream writing.

4. **Automated Partition Carver & Forensic Extractor:**
   * Decodes MBR / EBR / GPT partition chains without requiring scatter files.
   * Identifies `ext4` (0x53EF magic) and `FAT32` (Android boot sector) structures.
   * Carves out `userdata.img`, `fat.img`, `android.img`, `cache.img`.
   * Unpacks file systems automatically using 7-Zip.

5. **Instant User Data Recovery:**
   * **Contacts:** Parses Android `contacts2.db` and exports directly to:
     * `rehber.vcf` (vCard 3.0 - one-click import into Android/iPhone/Google Contacts)
     * `rehber.csv` (Excel / spreadsheet compatible)
     * `rehber.txt` (Human readable plain text)
   * **SMS Messages:** Parses `mmssms.db` into formatted chronological text logs with timestamps and sender IDs.
   * **Media:** Gathers camera photos, screenshots (`Pictures/Screenshots`), and documents into a clean quick-access folder.
   * **Accounts:** Discovers configured Google / email accounts (`accounts.db`).

---

## 📊 Status & Roadmap: Completed vs. Needed for Newer Processors

### ✅ Yapılanlar / Mevcut Yetenekler (Completed)
- [x] **BROM Düzeyinde Otomatik Port Yakalama & Handshake:** USB bağlantısını anlık yakalayan agresif `0xA0 0x0A 0x50 0x05` döngüsü.
- [x] **Donanım Algılama:** BROM üzerinden işlemci donanım kodunu (`hwcode`), versiyonu ve güvenlik bayraklarını (`SBC`, `SLA`, `DAA`) sorgulama.
- [x] **Watchdog Timer Kapatma:** Donanımsal 32 saniyelik PMIC kapanma zaman aşımını register düzeyinde devre dışı bırakma.
- [x] **DRAM / EMI Eşleştirme:** eMMC CID numarasına göre doğru RAM zamanlama kaydını seçerek DA2'yi başarıyla başlatma.
- [x] **Kararlı eMMC Dump Motoru:** 16 MB tekil DA komut sınırını aşan, 8 MB'lık parçalı okuma ve anlık diske yazma mimarisi (`wf.flush()`).
- [x] **Bağımsız Bölüm Dilimleme (Carving):** Scatter dosyasına ihtiyaç duymadan MBR/EBR, ext4 superblock (0x53EF) ve FAT32 boot sektörlerini ayrıştırma.
- [x] **Otomatik Dosya Sistemi Açma:** 7-Zip ile sembolik link hatalarını yutarak tüm gerçek dosyaları dışarı aktarma.
- [x] **Rehber ve SMS Kurtarma:** `contacts2.db` ve `mmssms.db` SQLite veritabanlarını VCF, CSV ve TXT formatlarına dönüştürme.
- [x] **Kripto Adli Bilişim Taraması:** Tüm sektörlerde Base58Check doğrulamalı Bitcoin adresleri, WIF özel anahtarları ve cüzdan izlerini arama.
- [x] **Taşınabilir CLI Arayüzü:** `--dump`, `--extract`, `--workdir` komut satırı argümanları.

---

### ⏳ Yeni Nesil İşlemciler İçin Geliştirilmesi Gerekenler (Roadmap / To-Do for Modern SoCs)

Modern MediaTek işlemciler (Helio P/G/X serisi ve Dimensity 700 / 800 / 900 / 1200 / 8000 / 9000 - MT67xx / MT68xx) için yapılması gereken geliştirmeler:

| # | Geliştirme Alanı | Mevcut Durum | Yeni İşlemciler İçin Gerekenler |
|---|---|---|---|
| 1 | **SLA / DAA Güvenlik Baypası** | Sadece korumasız BROM destekliyor (`SLA=False`, `DAA=False`). | **BROM Exploit Entegrasyonu:** Modern MTK çiplerinde kriptografik imza doğrulaması vardır. *Kamakiri* veya *Amonet* gibi USB buffer overflow açıklarını kullanan payload enjeksiyonu entegre edilmelidir. |
| 2 | **64-bit Download Agent (DA3)** | 32-bit Legacy DA (`MTK_AllInOne_DA_mt6590.bin`) kullanılıyor. | **Modern DA Yükleyici:** 64-bit mimariye sahip `MTK_DA_V5.bin` ve `MTK_DA_V6.bin` loader'ları ile XML tabanlı modern DA komut protokolü eklenmelidir. |
| 3 | **UFS Depolama Desteği** | Yalnızca eMMC User Area okunabiliyor. | **UFS LUN Mimarisi:** Dimensity ve üst seviye Helio cihazlar eMMC yerine UFS 2.1/3.1 bellek kullanır. `lu0`, `lu1`, `lu2` mantıksal birimlerini (LUN) okuma desteği eklenmelidir. |
| 4 | **GPT (GUID Partition Table)** | Yalnızca MBR / EBR zincirini çözümlüyor. | **Dinamik GPT Parser:** Android 7+ ve 64-bit cihazlarda MBR yerine GPT (128 bölüm girdili, LBA 1) kullanılır. `boot_a`, `system_a`, `super`, `userdata` bölümlerini GPT başlığından okuyan ayrıştırıcı eklenmelidir. |
| 5 | **Modern Dosya Sistemleri (F2FS & EROFS)** | Yalnızca ext4 ve FAT32 çözümleniyor. | **F2FS & EROFS Ayrıştırıcı:** Android 10+ cihazlarda `/data` bölümü çoğunlukla F2FS, sistem bölümleri ise EROFS formatındadır. Bu dosya sistemlerini açacak Python veya CLI kütüphaneleri dahil edilmelidir. |
| 6 | **Dinamik Watchdog Tablosu** | Sabit MT6582 register'ı (`0x10007000`) kullanılıyor. | **SoC-Spesifik WDT Haritası:** Her işlemci ailesinin (MT6765, MT6785, MT6877 vb.) PMIC/WDT kontrol adresi farklıdır. Çip koduna göre dinamik register seçim tablosu eklenmelidir. |
| 7 | **FBE (Dosya Tabanlı Şifreleme) Tespiti** | Şifrelenmemiş Android 4.x/5.x verilerini açıyor. | **FBE Uyarısı & Durum Tespiti:** Android 7 ve sonrası cihazlarda `/data` bölümü kullanıcı şifresiyle File-Based Encryption (FBE) olarak şifrelenir. Dump analizi sırasında FBE kilit durumunu tespit edip kullanıcıyı bilgilendiren modül eklenmelidir. |

---

## ⚙️ Requirements

* **Python 3.9+** (64-bit recommended)
* **PySerial:**
  ```bash
  pip install pyserial
  ```
* **7-Zip:** Installed at `C:\Program Files\7-Zip\7z.exe` or available in `PATH`.
* **MTK VCOM / Preloader Drivers:** MediaTek USB VCOM driver installed on Windows.

---

## 📖 CLI Usage

### 1. Full Automatic Dump (Connect Device via USB)
```bash
python auto_dumper.py --dump
```
*Listens for USB connection, performs handshake, halts watchdog timer, uploads DA, dumps physical eMMC, and automatically unpacks all user data.*

### 2. Extract Data from an Existing `.bin` Dump File
```bash
python auto_dumper.py --extract C:\path\to\dump.bin --workdir ./output_folder
```

### 3. Custom Preloader & DA Loader
```bash
python auto_dumper.py --dump --preloader ./preloader.bin --da ./DA.bin --out ./device_backup.bin
```

---

## ⚖️ License
Released under the MIT License. For educational and authorized digital forensics / data recovery use only.

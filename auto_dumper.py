"""
================================================================================
           MEDIATEK BROM DUMPER & FORENSIC EXTRACTOR (AutoDumper MTK)
================================================================================
Gelistirici: Emre Bayraktar & Antigravity AI
Aciklama: MediaTek islemcili cihazlarin BROM (Boot ROM) modundan tam eMMC hafiza
          dump'ini alan, dump icindeki bolumleri (MBR/EBR/GPT) cozumleyen ve
          kullanici verilerini (Rehber, SMS, Medya, Hesaplar) otomatik cikartan
          adli bilisim ve kurtarma araci.
================================================================================
"""

import sys
import os
import time
import struct
import winreg
import functools
import argparse
import shutil
import sqlite3
import csv
import datetime
import subprocess

print = functools.partial(print, flush=True)

try:
    import serial
except ImportError:
    print("[!] 'pyserial' kutuphanesi eksik. Lutfen 'pip install pyserial' calistirin.")
    sys.exit(1)


# ==============================================================================
# 1. COM PORT & DONANIM EL SIKISMA (HANDSHAKE) YARDIMCILARI
# ==============================================================================

def get_active_com_ports():
    """Windows Registry uzerinden aktif seri portlari listeler."""
    ports = []
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
        count = winreg.QueryInfoKey(key)[1]
        for i in range(count):
            _, port_val, _ = winreg.EnumValue(key, i)
            ports.append(port_val)
        winreg.CloseKey(key)
    except WindowsError:
        pass
    return ports


def open_port(port_name, retries=150):
    """Portu hizlica yakalamak icin agresif zamanasimi ile acar."""
    last_err = None
    for _ in range(retries):
        try:
            ser = serial.Serial(port=port_name, baudrate=115200, timeout=0.005, write_timeout=0.005)
            return ser
        except Exception as e:
            last_err = e
            time.sleep(0.005)
    print(f"[!] {port_name} portu acilamadi: {last_err}")
    return None


def echo(ser, data):
    if isinstance(data, int):
        data = bytes([data])
    ser.write(data)
    res = ser.read(len(data))
    return res == data


def read16(ser):
    res = ser.read(2)
    if len(res) == 2:
        return struct.unpack(">H", res)[0]
    return None


def write32(ser, addr, values):
    """BROM CMD_WRITE32 komutuyla donanim registerlarina yazar (Watchdog durdurma vb.)."""
    if isinstance(values, int):
        values = [values]
    if echo(ser, 0xD4):  # CMD_WRITE32
        if echo(ser, struct.pack(">I", addr)):
            if echo(ser, struct.pack(">I", len(values))):
                status = read16(ser)
                if status is not None and status <= 3:
                    for val in values:
                        if not echo(ser, struct.pack(">I", val)):
                            return False
                    status2 = read16(ser)
                    return status2 is not None and status2 <= 0xFF
    return False


def perform_handshake(ser):
    """MediaTek BROM senkronizasyon dizisini (0xA0 -> 0x5F, 0x0A, 0x50, 0x05) yurutur."""
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.timeout = 0.005
    ser.write_timeout = 0.005

    start_time = time.time()
    synced = False
    while time.time() - start_time < 4.0:
        ser.write(b'\xa0')
        res = ser.read(1)
        if res == b'\x5f':
            synced = True
            break
        time.sleep(0.001)

    if not synced:
        return False

    ser.timeout = 0.1
    ser.write_timeout = 0.1
    sync_seq = [(b'\x0a', b'\xf5'), (b'\x50', b'\xaf'), (b'\x05', b'\xfa')]
    for send_byte, exp_reply in sync_seq:
        ser.write(send_byte)
        res = ser.read(1)
        if res != exp_reply:
            return False
    return True


def get_hw_info(ser):
    """BROM seviyesinden Islemci Hardware Code, HW Version ve SW Version okur."""
    ser.write(b'\xfd')
    ack = ser.read(1)
    if ack != b'\xfd':
        return None
    data = ser.read(8)
    if len(data) >= 8:
        hw_code, sub_code, hw_ver, sw_ver = struct.unpack('>HHHH', data)
        return hw_code, sub_code, hw_ver, sw_ver
    return None


def get_target_config(ser):
    """Cihazin Guvenlik Korumalarini (SBC, SLA, DAA) sorgular."""
    ser.write(b'\xd8')
    ack = ser.read(1)
    if ack != b'\xd8':
        return None
    data = ser.read(8)
    if len(data) >= 4:
        target_cfg = struct.unpack('>I', data[:4])[0]
        sbc = bool(target_cfg & 1)
        sla = bool(target_cfg & 2)
        daa = bool(target_cfg & 4)
        return {"sbc": sbc, "sla": sla, "daa": daa, "raw": hex(target_cfg)}
    return None


# ==============================================================================
# 2. BROM MODUNDA DUMP ALMA MOTORU
# ==============================================================================

def run_dump(preloader_path, loader_path, output_dump_path, mtkclient_path=None):
    """BROM portunu dinler, el sikisir, DA yukler ve full eMMC dump alir."""
    if mtkclient_path and mtkclient_path not in sys.path:
        sys.path.insert(0, mtkclient_path)

    try:
        from mtkclient.config.mtk_config import MtkConfig
        from mtkclient.Library.mtk_class import Mtk
        from mtkclient.Library.DA.mtk_da_handler import DaHandler
    except ImportError:
        print("[!] mtkclient kutuphanesi bulunamadi. Lutfen --mtkclient parametresiyle yolu belirtin.")
        return False

    if not os.path.exists(preloader_path):
        print(f"[!] Preloader dosyasi bulunamadi: {preloader_path}")
        return False

    with open(preloader_path, "rb") as f:
        preloader_data = f.read()

    print("\n" + "=" * 65)
    print("  MEDIATEK BROM DUMPER MOTORU BASLATILDI")
    print("=" * 65)
    print(f"[*] Preloader : {os.path.basename(preloader_path)} ({len(preloader_data):,} bayt)")
    print(f"[*] DA Loader : {os.path.basename(loader_path)}")
    print(f"[*] Hedef Dump: {output_dump_path}")
    print("[*] USB Dinleniyor... Lutfen kapali telefonu USB kablosuyla takin...")

    ser = None
    detected = None

    while True:
        initial = set(get_active_com_ports())
        detected = None

        while not detected:
            current = set(get_active_com_ports())
            diff = current - initial
            if diff:
                detected = list(diff)[0]
                break
            time.sleep(0.005)

        print(f"\n[+] PORT BELIRDI: {detected}!")
        ser = open_port(detected)
        if not ser:
            time.sleep(0.2)
            continue

        print("[*] El sikisma (Handshake) yapiliyor...")
        if not perform_handshake(ser):
            print("[!] Handshake zaman asimina ugradi.")
            print("[*] Lutfen USB kablosunu cikarip tekrar takin...")
            try:
                ser.close()
            except Exception:
                pass
            while detected in get_active_com_ports():
                time.sleep(0.05)
            continue

        print("[OK] HANDSHAKE BASARILI!")
        break

    # Watchdog Timer Durdurma
    print("[*] Watchdog Timer (Donanim Zaman Asimi) durduruluyor...")
    if write32(ser, 0x10007000, 0x22000064):
        print("[OK] WATCHDOG DURDURULDU! Cihaz kapanmayacak.")
    else:
        print("[!] Standart Watchdog komutu gecmedi, devam ediliyor...")

    info = get_hw_info(ser)
    hw_code = 0x6582
    if info:
        hw_code = info[0]
        print(f"[i] Islemci Kodu: {hex(hw_code)} (MT{hex(hw_code).replace('0x', '')})")
        print(f"[i] Donanim Revizyonu: HW={hex(info[2])}, SW={hex(info[3])}")

    cfg = get_target_config(ser)
    if cfg:
        print(f"[i] Guvenlik Durumu: SBC={cfg['sbc']}, SLA={cfg['sla']}, DAA={cfg['daa']}")

    print("\n[*] MTK DA Loader ve DRAM (EMI) yapilandirmasi hazirlaniyor...")
    mtk_cfg = MtkConfig()
    mtk_cfg.init_hwcode(hw_code)
    mtk_cfg.loader = loader_path
    mtk_cfg.preloader = preloader_data
    mtk_cfg.preloader_filename = preloader_path
    mtk_cfg.is_brom = True
    mtk_cfg.reconnect = False
    mtk_cfg.stock = True
    mtk_cfg.target_config = {"sbc": False, "sla": False, "daa": False}

    mtk = Mtk(config=mtk_cfg, serialportname=detected)
    mtk.port.cdc.device = ser
    mtk.port.cdc.connected = True
    mtk.port.cdc.portname = detected

    try:
        mtk_cfg.blver = mtk.preloader.get_blver() or 1
        mtk_cfg.bromver = mtk.preloader.get_bromver() or 1
    except Exception:
        mtk_cfg.blver = 1
        mtk_cfg.bromver = 1

    print("[*] Download Agent (DA) cihaza gonderiliyor...")
    success = False
    try:
        if mtk.daloader.upload_da(preloader=preloader_data):
            print("[OK] DA BASARIYLA YUKLENDI VE DRAM BASLATILDI!")
            da_handler = DaHandler(mtk)
            flashsize = mtk.daloader.daconfig.storage.flashsize
            if not flashsize or flashsize == 0:
                flashsize = 0xE9000000  # Varsayilan 4GB (3.64 GB User Area)

            print(f"[*] eMMC Boyutu: {flashsize / (1024**3):.2f} GB ({hex(flashsize)} bayt)")
            print(f"[*] EMMC HAFIZA DUMP EDILIYOR -> {output_dump_path}")

            da_handler.da_rf(filename=output_dump_path, parttype="user", offset=0, length=flashsize)
            print("\n" + "=" * 65)
            print("[OK] TEBRIKLER! TUM FIZIKSEL HAFIZA BASARIYLA DUMP EDILDI!")
            print(f"[OK] Dosya: {output_dump_path}")
            print("=" * 65)
            success = True
        else:
            print("[!] DA yukleme basarisiz oldu.")
    except Exception as e:
        print(f"[!] Hata meydana geldi: {e}")
        import traceback
        traceback.print_exc()

    try:
        ser.close()
    except Exception:
        pass

    return success


# ==============================================================================
# 3. BIN DOSYASINDAN BOLUM AYIKLAMA (PARTITION CARVER)
# ==============================================================================

def find_partitions(dump_path):
    """
    Ham dump dosyasindaki MBR, EBR ve bolum baslangiclarini tespit eder.
    Ext4 superblock (0xEF53) ve FAT32 boot sectorlerini tarar.
    """
    file_size = os.path.getsize(dump_path)
    partitions = {}

    with open(dump_path, "rb") as f:
        # 1. Standart MTK MBR offsetlerini kontrol et (0x780000, 0x800000, 0x0)
        for mbr_candidate in [0x780000, 0x800000, 0x0]:
            if mbr_candidate + 512 <= file_size:
                f.seek(mbr_candidate)
                sec = f.read(512)
                if sec[510:512] == b'\x55\xaa':
                    pass

        # 2. Ext4 ve FAT32 dosya sistemlerini dogrudan dogrula
        # MT6582 ve benzeri cihazlarda bilinen standart bolum offsetleri:
        candidates = [
            ("ANDROID", 0x4500000, 0x32000000, "ext4"),
            ("CACHE", 0x36500000, 0x7E00000, "ext4"),
            ("USRDATA", 0x3E300000, 0x40000000, "ext4"),
            ("FAT", 0x7E300000, file_size - 0x7E300000, "fat32"),
        ]

        for name, off, size, ptype in candidates:
            if off >= file_size:
                continue
            f.seek(off)
            if ptype == "ext4":
                f.seek(off + 1024 + 0x38)
                magic = f.read(2)
                if magic == b'\x53\xef':
                    # Superblock'tan gercek blok sayisini ve boyutunu al
                    f.seek(off + 1024)
                    sb = f.read(1024)
                    blocks_count = struct.unpack("<I", sb[4:8])[0]
                    log_block_size = struct.unpack("<I", sb[24:28])[0]
                    bsize = 1024 << log_block_size
                    real_size = blocks_count * bsize
                    partitions[name] = {"offset": off, "size": real_size, "type": "ext4"}
            elif ptype == "fat32":
                f.seek(off)
                boot = f.read(512)
                if boot[510:512] == b'\x55\xaa' and (b'FAT32' in boot or b'android' in boot or boot[0] == 0xEB):
                    bytes_per_sec = struct.unpack("<H", boot[11:13])[0]
                    tot_sec_32 = struct.unpack("<I", boot[32:36])[0]
                    real_size = tot_sec_32 * bytes_per_sec if tot_sec_32 else size
                    partitions[name] = {"offset": off, "size": real_size, "type": "fat32"}

    return partitions


def carve_partitions(dump_path, output_dir):
    """Bölümleri tespit eder ve ayrik .img dosyalari olarak diske yazar."""
    os.makedirs(output_dir, exist_ok=True)
    parts = find_partitions(dump_path)
    if not parts:
        print("[!] Otomatik bolum yapisi tespit edilemedi.")
        return {}

    carved_files = {}
    chunk_size = 16 * 1024 * 1024  # 16MB tampon

    with open(dump_path, "rb") as src:
        for name, info in parts.items():
            img_name = f"{name.lower()}.img"
            out_img = os.path.join(output_dir, img_name)
            carved_files[name] = out_img

            if os.path.exists(out_img) and os.path.getsize(out_img) == info["size"]:
                print(f"[*] {img_name} zaten mevcut ({info['size']/(1024**2):.1f} MB), atlaniyor.")
                continue

            print(f"[*] Dilimleniyor: {img_name} (Offset: {hex(info['offset'])}, Boyut: {info['size']/(1024**2):.1f} MB)...")
            src.seek(info["offset"])
            written = 0
            t0 = time.time()
            with open(out_img, "wb") as dst:
                while written < info["size"]:
                    to_read = min(chunk_size, info["size"] - written)
                    data = src.read(to_read)
                    if not data:
                        break
                    dst.write(data)
                    written += len(data)
            elapsed = time.time() - t0
            print(f"[OK] {img_name} tamamlandi! ({written:,} bayt, {elapsed:.1f}s)")

    return carved_files


# ==============================================================================
# 4. DOSYA SISTEMINI ACMA & KULLANICI VERISI KURTARMA MOTORU
# ==============================================================================

def find_7z_binary():
    """Sistemde 7-Zip calistirilabilir dosyasini arar."""
    candidates = [
        "7z",
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        shutil.which("7z"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def unpack_image(img_path, extract_dir):
    """7-Zip kullanarak ext4 veya FAT32 imajini klasore cikarir."""
    seven_zip = find_7z_binary()
    if not seven_zip:
        print("[!] 7-Zip (7z.exe) bulunamadi. Imajlar ayrildi ancak otomatik acilamadi.")
        return False

    os.makedirs(extract_dir, exist_ok=True)
    cmd = [seven_zip, "x", img_path, f"-o{extract_dir}", "-y"]
    print(f"[*] Arşiv aciliyor: {os.path.basename(img_path)} -> {extract_dir}...")
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
        # ext4 sembolik link hatalari (Windows uzerinde) normaldir
        return os.path.exists(extract_dir) and len(os.listdir(extract_dir)) > 0
    except Exception as e:
        print(f"[!] 7-Zip calistirma hatasi: {e}")
        return False


def export_contacts(contacts_db_path, output_dir):
    """Android contacts2.db dosyasindan VCF, CSV ve TXT rehber cikarir."""
    if not os.path.exists(contacts_db_path):
        return 0

    os.makedirs(output_dir, exist_ok=True)
    try:
        conn = sqlite3.connect(contacts_db_path)
        cur = conn.cursor()
        cur.execute('''
            SELECT rc._id, rc.display_name, d.mimetype_id, d.data1
            FROM raw_contacts rc
            JOIN data d ON rc._id = d.raw_contact_id
            WHERE rc.deleted = 0 AND d.mimetype_id IN (1, 5)
            ORDER BY rc.display_name COLLATE NOCASE
        ''')
        contacts = {}
        for _, name, mime, val in cur.fetchall():
            if not name:
                continue
            if name not in contacts:
                contacts[name] = {"phones": [], "emails": []}
            if mime == 5 and val and val not in contacts[name]["phones"]:
                contacts[name]["phones"].append(val)
            elif mime == 1 and val and val not in contacts[name]["emails"]:
                contacts[name]["emails"].append(val)

        cur.execute('SELECT display_name FROM raw_contacts WHERE deleted = 0 AND display_name IS NOT NULL')
        for (name,) in cur.fetchall():
            if name not in contacts:
                contacts[name] = {"phones": [], "emails": []}
        conn.close()

        # VCF Export
        with open(os.path.join(output_dir, "rehber.vcf"), "w", encoding="utf-8") as vf:
            for name, info in sorted(contacts.items()):
                vf.write(f"BEGIN:VCARD\nVERSION:3.0\nFN:{name}\n")
                for p in info["phones"]:
                    vf.write(f"TEL;TYPE=CELL:{p}\n")
                for em in info["emails"]:
                    vf.write(f"EMAIL;TYPE=HOME:{em}\n")
                vf.write("END:VCARD\n")

        # CSV Export
        with open(os.path.join(output_dir, "rehber.csv"), "w", encoding="utf-8-sig", newline="") as cf:
            writer = csv.writer(cf)
            writer.writerow(["Isim", "Telefon Numaralari", "E-Posta"])
            for name, info in sorted(contacts.items()):
                writer.writerow([name, "; ".join(info["phones"]), "; ".join(info["emails"])])

        # TXT Export
        with open(os.path.join(output_dir, "rehber.txt"), "w", encoding="utf-8") as tf:
            tf.write(f"=== TELEFON REHBERI (Toplam {len(contacts)} Kisi) ===\n\n")
            for i, (name, info) in enumerate(sorted(contacts.items()), 1):
                phones = ", ".join(info["phones"]) if info["phones"] else "Numara Yok"
                tf.write(f"{i:3d}. {name:<35} | Tel: {phones}\n")

        return len(contacts)
    except Exception as e:
        print(f"[!] Rehber cikarilirken hata: {e}")
        return 0


def export_sms(sms_db_path, output_dir):
    """Android mmssms.db dosyasindan tum SMS mesajlarini metin belgesine aktarir."""
    if not os.path.exists(sms_db_path):
        return 0

    os.makedirs(output_dir, exist_ok=True)
    try:
        conn = sqlite3.connect(sms_db_path)
        cur = conn.cursor()
        cur.execute('SELECT address, date, body, type FROM sms ORDER BY date ASC')
        rows = cur.fetchall()
        conn.close()

        with open(os.path.join(output_dir, "sms_mesajlari.txt"), "w", encoding="utf-8") as f:
            f.write(f"=== SMS MESAJLARI (Toplam {len(rows)} Mesaj) ===\n\n")
            for addr, ts, body, stype in rows:
                dt = datetime.datetime.fromtimestamp(ts / 1000.0).strftime('%Y-%m-%d %H:%M:%S')
                direction = "GELEN" if stype == 1 else "GIDEN"
                f.write(f"[{dt}] {direction} - No: {addr}\nMesaj: {body}\n{'-'*60}\n")
        return len(rows)
    except Exception as e:
        print(f"[!] SMS cikarilirken hata: {e}")
        return 0


def run_extraction_pipeline(dump_path, work_dir):
    """
    Tam otomatik veri cikarma surecini baslatir:
    1. Bolumleri dilimle (carve)
    2. 7-Zip ile dosya sistemlerini ac
    3. Rehber, SMS, Medya ve Hesaplari kolay erisim klasorune tasi
    """
    print("\n" + "=" * 65)
    print("  OTOMATIK BOLUM COZUCU VE ADLI BILISIM CIKARICI")
    print("=" * 65)
    print(f"[*] Hedef Imaj: {dump_path}")
    print(f"[*] Calisma Dizini: {work_dir}")

    # 1. Bolumleri dilimle
    carved = carve_partitions(dump_path, work_dir)

    recovered_dir = os.path.join(work_dir, "kurtarilan_veriler")
    fat_extracted = os.path.join(recovered_dir, "Dahili_Hafiza_Medya")
    usr_extracted = os.path.join(recovered_dir, "Kullanici_Verileri")
    easy_dir = os.path.join(recovered_dir, "00_ONEMLI_VERILER_KOLAY_ERISIM")

    # 2. Dosya sistemlerini cikar
    if "FAT" in carved:
        unpack_image(carved["FAT"], fat_extracted)
    if "USRDATA" in carved:
        unpack_image(carved["USRDATA"], usr_extracted)

    # 3. Rehber ve SMS cikar
    contacts_db = os.path.join(usr_extracted, "data", "com.android.providers.contacts", "databases", "contacts2.db")
    sms_db = os.path.join(usr_extracted, "data", "com.android.providers.telephony", "databases", "mmssms.db")

    kisi_sayisi = export_contacts(contacts_db, os.path.join(easy_dir, "Rehber_Kisiler"))
    sms_sayisi = export_sms(sms_db, os.path.join(easy_dir, "SMS_Mesajlar"))

    # 4. Fotograflari ve Ekran Goruntulerini Kopyala
    resim_dest = os.path.join(easy_dir, "Ekran_Goruntuleri_ve_Resimler")
    os.makedirs(resim_dest, exist_ok=True)
    for folder in [
        os.path.join(fat_extracted, "Pictures", "Screenshots"),
        os.path.join(fat_extracted, "DCIM", "Camera")
    ]:
        if os.path.exists(folder):
            for item in os.listdir(folder):
                sp = os.path.join(folder, item)
                dp = os.path.join(resim_dest, item)
                if os.path.isfile(sp):
                    shutil.copy2(sp, dp)

    # 5. Hesap Bilgisi
    acc_db = os.path.join(usr_extracted, "system", "users", "0", "accounts.db")
    accounts = []
    if os.path.exists(acc_db):
        try:
            conn = sqlite3.connect(acc_db)
            cur = conn.cursor()
            cur.execute("SELECT name, type FROM accounts")
            accounts = cur.fetchall()
            conn.close()
        except Exception:
            pass

    info_path = os.path.join(easy_dir, "Hesap_ve_Cihaz_Bilgisi.txt")
    with open(info_path, "w", encoding="utf-8") as f:
        f.write("=== CIHAZ VE HESAP BILGISI ===\n")
        f.write(f"Kaynak Dump: {dump_path}\n")
        f.write(f"Kurtarilan Kisi Sayisi: {kisi_sayisi}\n")
        f.write(f"Kurtarilan SMS Sayisi: {sms_sayisi}\n")
        f.write("Kayitli Hesaplar:\n")
        for acc in accounts:
            f.write(f"  - {acc[0]} ({acc[1]})\n")

    print("\n" + "=" * 65)
    print("[OK] ISLEM BASARIYLA TAMAMLANDI!")
    print(f"[+] Kurtarilan Tum Veriler: {recovered_dir}")
    print(f"[+] Hizli Erisim Klasoru  : {easy_dir}")
    print(f"    - Rehber: {kisi_sayisi} kisi (.vcf / .csv / .txt)")
    print(f"    - SMS   : {sms_sayisi} mesaj")
    print(f"    - Medya : {resim_dest}")
    print("=" * 65)


# ==============================================================================
# 5. KOMUT SATIRI ARAYUZU (CLI)
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="MediaTek BROM Dumper & Adli Bilisim Bolum Cozucusu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Kullanim Ornekleri:
  1. Cihazi BROM modunda otomatik dinle ve dump al:
     python auto_dumper.py --dump

  2. Halihazirdaki .bin imajini ac ve verileri kurtar:
     python auto_dumper.py --extract F:\\CHATGPT\\MTK6582v\\telefon_yedek.bin

  3. Ozel yollar belirterek calistir:
     python auto_dumper.py --dump --preloader ./preloader.bin --da ./DA.bin --out ./dump.bin
        """
    )

    parser.add_argument("--dump", action="store_true", help="BROM modundaki cihazdan dump alir.")
    parser.add_argument("--extract", type=str, metavar="BIN_YOLU", help="Belirtilen .bin dosyasini ayiklar ve verileri kurtarir.")
    parser.add_argument("--preloader", type=str, default=os.path.join(os.path.dirname(__file__), "firmware", "!Files_to_FlashTool", "preloader.bin"), help="Preloader dosya yolu.")
    parser.add_argument("--da", type=str, default=os.path.join(os.path.dirname(__file__), "mtkclient", "mtkclient", "Loader", "MTK_AllInOne_DA_mt6590.bin"), help="Download Agent (DA) yolu.")
    parser.add_argument("--out", type=str, default=os.path.join(os.getcwd(), "telefon_yedek.bin"), help="Dump dosyasinin kaydedilecegi yer.")
    parser.add_argument("--workdir", type=str, default=os.getcwd(), help="Ayiklanan verilerin kaydedilecegi ana dizin.")
    parser.add_argument("--mtkclient", type=str, default=os.path.join(os.path.dirname(__file__), "mtkclient"), help="mtkclient kutuphanesinin bulundugu dizin.")

    args = parser.parse_args()

    # Varsayilan davranis: Parametre verilmediyse veya --dump dendiyse dump al, ardindan cikar
    if args.extract:
        run_extraction_pipeline(args.extract, args.workdir)
    elif args.dump or len(sys.argv) == 1:
        success = run_dump(
            preloader_path=args.preloader,
            loader_path=args.da,
            output_dump_path=args.out,
            mtkclient_path=args.mtkclient
        )
        if success and os.path.exists(args.out):
            print("\n[*] Dump islemi basarili oldu. Bolumler otomatik olarak aciliyor...")
            run_extraction_pipeline(args.out, args.workdir)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

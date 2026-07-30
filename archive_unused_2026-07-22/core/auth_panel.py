# -*- coding: utf-8 -*-
import sys
import os

# core klasörünü Python arama yoluna ekle
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.database import DatabaseManager

class AtlasAuthPanel:
    def __init__(self):
        self.db = DatabaseManager()
        self.current_user = None

    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def run(self):
        while True:
            self.clear_screen()
            print("====================================================")
            print("         ATLAS AI - KULLANICI GİRİŞ SİSTEMİ         ")
            print("====================================================")
            print("1. Giriş Yap")
            print("2. Çıkış")
            print("====================================================")
            choice = input("Seçiminiz (1-2): ").strip()

            if choice == "1":
                self.login()
            elif choice == "2":
                print("\n[Sistem] Atlas AI kapatılıyor. Güvenli günler!")
                break
            else:
                input("\n[Hata] Geçersiz seçim. Devam etmek için Enter'a basın...")

    def login(self):
        self.clear_screen()
        print("====================================================")
        print("                    GİRİŞ EKRANI                    ")
        print("====================================================")
        username = input("Kullanıcı Adı: ").strip()
        password = input("Şifre        : ").strip()

        user = self.db.authenticate_user(username, password)

        if user:
            self.current_user = dict(user)
            print(f"\n[Başarılı] Giriş yapıldı! Hoş geldiniz, {self.current_user['username']}.")
            input("Devam etmek için Enter'a basın...")
            
            if self.current_user['role'] == 'admin':
                self.show_admin_panel()
            else:
                self.show_user_panel()
        else:
            input("\n[Hata] Kullanıcı adı veya şifre hatalı! Devam etmek için Enter'a basın...")

    # ==================== YÖNETİCİ (ADMIN) PANELİ ====================
    def show_admin_panel(self):
        while True:
            self.clear_screen()
            print("====================================================")
            print(f"      ATLAS AI - MERKEZİ YÖNETİCİ KONTROL PANELİ     ")
            print(f"      Aktif Yönetici: {self.current_user['username']}   ")
            print("====================================================")
            print("1. Tüm Kullanıcıları ve Durumlarını Görüntüle")
            print("2. Yeni Kullanıcı Hesabı Tanımla")
            print("3. Sistem Genel Risk Ayarlarını Güncelle (Sadece Admin)")
            print("4. ANLIK AKTİF POZİSYONLARI İZLE (CANLI)")
            print("5. Oturumu Kapat")
            print("====================================================")
            choice = input("Seçiminiz (1-5): ").strip()

            if choice == "1":
                self.admin_view_users()
            elif choice == "2":
                self.admin_create_user()
            elif choice == "3":
                self.admin_risk_settings()
            elif choice == "4":
                self.admin_monitor_live_trades()
            elif choice == "5":
                self.current_user = None
                break
            else:
                input("\n[Hata] Geçersiz seçim. Devam etmek için Enter'a basın...")

    def admin_view_users(self):
        self.clear_screen()
        print("=====================================================================")
        print("                     KULLANICI RAPORLARI VE PnL                      ")
        print("=====================================================================")
        users = self.db.admin_get_all_users_with_trades()
        
        print(f"{'ID':<4} | {'Kullanıcı Adı':<18} | {'Rol':<8} | {'Top. İşlem':<10} | {'Kazanılan':<9} | {'Net PnL (USD)'}")
        print("-" * 69)
        
        for u in users:
            usr = dict(u)
            pnl_val = usr['total_pnl'] if usr['total_pnl'] is not None else 0.0
            print(f"{usr['id']:<4} | {usr['username']:<18} | {usr['role']:<8} | {usr['total_trades']:<10} | {usr['win_trades']:<9} | {pnl_val:+.2f} USD")
            
        print("=====================================================================")
        input("\nGeri dönmek için Enter'a basın...")

    def admin_create_user(self):
        self.clear_screen()
        print("====================================================")
        print("                YENİ KULLANICI KAYDI                ")
        print("====================================================")
        new_username = input("Kullanıcı Adı: ").strip()
        new_password = input("Şifre        : ").strip()
        new_role = input("Rol (user/admin) [Varsayılan: user]: ").strip().lower()
        if new_role not in ["user", "admin"]:
            new_role = "user"

        success = self.db.register_user(new_username, new_password, new_role)
        if success:
            print(f"\n[Sistem] Hesap başarıyla oluşturuldu!")
        input("\nGeri dönmek için Enter'a basın...")

    def admin_risk_settings(self):
        self.clear_screen()
        print("====================================================")
        print("             SİSTEM GENEL RİSK AYARLARI             ")
        print("====================================================")
        print("[Mevcut Durum] Maksimum Kaldıraç Sınırı: 5x")
        print("[Mevcut Durum] Maksimum Tek İşlem Riski: %2")
        print("----------------------------------------------------")
        print("⚠️ Sistem genelindeki bu ayarları sadece siz değiştirebilirsiniz.")
        input("\n[Bilgi] Bu modül geliştirme aşamasındadır. Geri dönmek için Enter'a basın...")

    def admin_monitor_live_trades(self):
        self.clear_screen()
        print("=====================================================================")
        print("                 SİSTEMDEKİ ANLIK AKTİF POZİSYONLAR                  ")
        print("=====================================================================")
        active_trades = self.db.admin_get_all_active_trades()
        
        if not active_trades:
            print("\nŞu anda sistemde açık olan aktif hiçbir pozisyon yok.")
        else:
            print(f"{'İşlem ID':<8} | {'Kullanıcı':<15} | {'Parite':<8} | {'Yön':<5} | {'Giriş Fiyatı':<12} | {'Miktar'}")
            print("-" * 69)
            for t in active_trades:
                trade = dict(t)
                print(f"{trade['id']:<8} | {trade['username']:<15} | {trade['symbol']:<8} | {trade['side']:<5} | {trade['price']:<12.2f} | {trade['amount']:.5f}")
        
        print("=====================================================================")
        input("\nGeri dönmek için Enter'a basın...")


    # ==================== KULLANICI PANELİ ====================
    def show_user_panel(self):
        while True:
            self.clear_screen()
            print("====================================================")
            print(f"            ATLAS AI - KULLANICI PANELİ             ")
            print(f"            Aktif Hesap: {self.current_user['username']}   ")
            print("====================================================")
            print("1. Binance TR API Anahtarlarımı Güncelle")
            print("2. Mevcut API Anahtarı Durumunu Sorgula") # Yeni Güvenlik Görünümü
            print("3. Aktif Pozisyonlarımı ve İşlem Geçmişimi Gör")
            print("4. Kasa Durumumu Sorgula")
            print("5. Oturumu Kapat")
            print("====================================================")
            choice = input("Seçiminiz (1-5): ").strip()

            if choice == "1":
                self.user_update_api()
            elif choice == "2":
                self.user_check_api_status()
            elif choice == "3":
                self.user_view_trades()
            elif choice == "4":
                self.user_view_balance()
            elif choice == "5":
                self.current_user = None
                break
            else:
                input("\n[Hata] Geçersiz seçim. Devam etmek için Enter'a basın...")

    def user_update_api(self):
        self.clear_screen()
        print("====================================================")
        print("             BİNANCE TR API TANIMLAMA               ")
        print("====================================================")
        print("⚠️ API anahtarlarınız veritabanında şifreli olarak tutulur.")
        print("Lütfen para çekme (withdraw) izni verilmemiş anahtar girin.")
        print("----------------------------------------------------")
        api_key = input("Binance TR API Key   : ").strip()
        api_secret = input("Binance TR API Secret: ").strip()

        if api_key and api_secret:
            # save_api_keys metodu arka planda AES-256-GCM kullanır
            self.db.save_api_keys(self.current_user['id'], api_key, api_secret)
            print("\n[Başarılı] API Anahtarlarınız AES-256-GCM ile şifrelenerek güvenle kaydedildi!")
        else:
            print("\n[Hata] Boş değer girilemez.")
        input("\nGeri dönmek için Enter'a basın...")

    def user_check_api_status(self):
        self.clear_screen()
        print("====================================================")
        print("             API ANAHTARI GÜVENLİK DURUMU           ")
        print("====================================================")
        
        # Veritabanından şifreli anahtarları çekip çözelim
        keys = self.db.get_api_keys(self.current_user['id'])
        
        if keys and keys['api_key'] and keys['api_secret']:
            # Güvenlik amacıyla anahtarın sadece ilk ve son 4 karakterini gösteriyoruz (Maskeleme)
            masked_key = f"{keys['api_key'][:4]}...{keys['api_key'][-4:]}"
            masked_secret = f"{keys['api_secret'][:4]}...{keys['api_secret'][-4:]}"
            
            print("🔒 Durum: ŞİFRELENMİŞ & AKTİF (AES-256-GCM)")
            print(f"Borsa: Binance TR")
            print(f"Maskeli API Key   : {masked_key}")
            print(f"Maskeli API Secret: {masked_secret}")
            print("----------------------------------------------------")
            print("Atlas AI bu anahtarları yalnızca canlı işlem sinyali")
            print("geldiğinde hafızada geçici olarak çözer, asla düz")
            print("metin olarak diske kaydetmez.")
        else:
            print("❌ Durum: API ANAHTARI TANIMLANMAMIŞ")
            print("Sistem şu anda sizin adınıza işlem gerçekleştiremez.")
            print("Lütfen menüden '1' numaralı seçeneği kullanarak tanımlayın.")
            
        print("====================================================")
        input("\nGeri dönmek için Enter'a basın...")

    def user_view_trades(self):
        self.clear_screen()
        print("====================================================")
        print("                AKTİF POZİSYONLARIM                 ")
        print("====================================================")
        print("Henüz aktif açık pozisyonunuz bulunmamaktadır.")
        print("----------------------------------------------------")
        input("\nGeri dönmek için Enter'a basın...")

    def user_view_balance(self):
        self.clear_screen()
        print("====================================================")
        print("                    KASA BİLGİSİ                    ")
        print("====================================================")
        print("Cüzdan Tipi: Binance TR Spot")
        print("Bakiye     : 1,000.00 USD (Sanal Simüle Portföy)")
        print("----------------------------------------------------")
        input("\nGeri dönmek için Enter'a basın...")

if __name__ == "__main__":
    panel = AtlasAuthPanel()
    panel.run()
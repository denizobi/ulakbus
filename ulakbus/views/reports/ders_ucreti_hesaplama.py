# -*-  coding: utf-8 -*-

# Copyright (C) 2015 ZetaOps Inc.
#
# This file is licensed under the GNU General Public License v3
# (GPLv3).  See LICENSE.txt for details.

from pyoko import ListNode
from zengine.views.crud import CrudView
from zengine.forms import fields
from zengine.forms import JsonForm
from ulakbus.models.ogrenci import Okutman, Donem, Takvim, Unit
from ulakbus.models.personel import Izin
from ulakbus.models.ders_programi_data import DersEtkinligi
from datetime import datetime, date
import calendar
from collections import OrderedDict
from ulakbus.lib.common import AYLAR, get_akademik_takvim

guncel_yil = datetime.now().year
guncel_ay = datetime.now().month

# Guncel donem ve 5 onceki yili tuple halinde YIL listesinde tutar.
YIL = []
for i in range(5):
    YIL.append((i, guncel_yil - i))


class TarihForm(JsonForm):
    """
    Puantaj tablosu hazırlanırken ay ve yıl seçiminde
    kullanılan form.
    """

    class Meta:
        title = 'Puantaj Tablosu Hazırlamak İstediğiniz Yıl ve Ayı Seçiniz'

    yil_sec = fields.String('Yıl Seçiniz', choices=YIL, default=0)
    ay_sec = fields.String('Ay Seçiniz', choices=AYLAR, default=guncel_ay)


class OkutmanListelemeForm(JsonForm):
    """
    Puantaj tablosu hazırlanacak olan okutmanların listesini
    gösteren form.
    """

    class Meta:
        inline_edit = ['secim']

    class OkutmanListesi(ListNode):
        secim = fields.Boolean("Seçim", type="checkbox")
        okutman = fields.String('Okutman', index=True)
        key = fields.String(hidden=True)


class DersUcretiHesaplama(CrudView):
    """
    Tüm okutmanların aylık olarak girdikleri derslerin
    ve ek derslerin saatlerini hesaplamaya yarayan iş akışı.
    Izin gunleri ve resmi tatil gunlerini de dikkate alir.
    """

    def tarih_sec(self):
        """
        Puantaj tablosunun hesaplanacağı ay ve yılı
        seçmeye yarar.
        """

        _form = TarihForm(current=self.current)
        _form.sec = fields.Button("İlerle")
        self.form_out(_form)

    def donem_kontrol(self):
        """
        Seçilen ay ve yıla ait dönem olup olmadığını kontrol eder.
        """

        self.current.task_data["yil"] = YIL[self.input['form']['yil_sec']][1]
        self.current.task_data["ay"] = self.input['form']['ay_sec']
        # guncel olan ayın ismi getirilir.
        self.current.task_data["ay_isim"] = AYLAR[self.input['form']['ay_sec'] - 1][1]

        takvim = calendar.monthrange(self.current.task_data["yil"], self.current.task_data["ay"])
        donem_list = Donem.donem_dondur(self.current.task_data["yil"], self.current.task_data["ay"], takvim)

        if len(donem_list) > 0:
            self.current.task_data['donem_sayi'] = True
        else:
            self.current.task_data['donem_sayi'] = False

    def donem_secim_uyari(self):
        """
        Eğer seçilen ay ve yıla ait dönem bulunamamışsa uyarı verir.
        2016 Güz dönemindeyken 2016 Temmuz ayı (Yaz Dönemi) için bir sorgu
        istenirse daha o dönem açılmadığından hata verecektir.
        """

        _form = JsonForm(current=self.current, title="Dönem Bulunamadı")
        _form.help_text = """Seçtiğiniz yıl ve aya ait dönem bulunamadı. Tarih
                          seçimine geri dönmek için Geri Dön butonuna, işlemi
                          iptal etmek için İptal butonuna basabilirsiniz."""
        _form.geri_don = fields.Button("Geri Dön", flow='tarih_sec')
        _form.iptal = fields.Button("İptal")
        self.form_out(_form)

    def okutman_sec(self):
        """
        Puantaj tablosunun hesaplanacağı okutmanların
        seçilmesine yarar. Bu okutmanlar işlem yapılan birime göre
        sorgulatılır. Bilgisayar Mühendisliği için yapılan sorguda
        sadece Bilgisayar Mühendisliği'nde bulunan okutmanlar ekrana
        gelecektir.
        """

        self.current.role.unit.yoksis_no = 207974  # it will be dynamic
        birim_no = self.current.role.unit.yoksis_no
        _form = OkutmanListelemeForm(current=self.current, title="Okutman Seçiniz")
        okutmanlar = Okutman.objects.filter(birim_no=birim_no)

        for okutman in okutmanlar:
            okutman_adi = okutman.ad + ' ' + okutman.soyad

            _form.OkutmanListesi(secim=True, okutman=okutman_adi, key=okutman.key)

        _form.sec = fields.Button("İlerle")
        self.form_out(_form)

    def ders_saati_turu_secme(self):
        """
        Ders Ücreti ya da Ek Ders Ücreti hesaplarından birini seçmeye yarar.
        """

        self.current.task_data["control"] = None
        secilen_okutmanlar = []
        for okutman_secim in self.current.input['form']['OkutmanListesi']:
            if okutman_secim['secim'] == True:
                secilen_okutmanlar.append(okutman_secim)

        self.current.task_data["secilen_okutmanlar"] = secilen_okutmanlar

        _form = JsonForm(current=self.current, title="Öğretim Görevlileri"
                                                     " Puantaj Tablosu Hesaplama"
                                                     "Türü Seçiniz")

        _form.ders = fields.Button("Ders Ücreti Hesapla", cmd='ders_ucreti_hesapla')
        _form.ek_ders = fields.Button("Ek Ders Ücreti Hesapla", cmd='ek_ders_ucreti_hesapla')
        self.form_out(_form)

    def ders_ucreti_hesapla(self):

        self.current.task_data["control"] = True

    def ek_ders_ucreti_hesapla(self):
        self.current.task_data["control"] = False

    def ucret_hesapla(self):
        """
        Seçilen ay ve yıla göre, seçilen her bir öğretim elemanının
        resmi tatil ve izinleri dikkate alarak aylık ders saati planlamasını
        yapar
        """

        yil = self.current.task_data["yil"]  # girilen yil
        ay = self.current.task_data["ay"]  # girilen ayin orderi
        ay_isim = self.current.task_data["ay_isim"]  # ayin adi

        takvim = calendar.monthrange(yil, ay)
        # verilen yıl ve aya göre tuple şeklinde ayın ilk gününü
        # ve ayın kaç gün sürdüğü bilgisini döndürür.
        # Ayın ilk günü = 0-6 Pazt-Pazar
        # 2016 yılı Temmuz ayı için = (4,31)

        birim_no = 207974  # rolden gelecek
        birim_unit = Unit.objects.get(yoksis_no=birim_no)

        # Verilen yıl ve birime göre akademik takvim döndürür

        # Secilen ay hangi donemleri kapsiyor, kac donemi kapsıyorsa
        # o donemleri dondürür.
        donem_list = Donem.donem_dondur(yil, ay, takvim)

        # Resmi tatilerin gununu donduruyor (23, 12, 8) gibi
        resmi_tatil_list, akademik_takvim_list = Takvim.resmi_tatil_gunleri_getir(donem_list, birim_unit, yil, ay)
        print akademik_takvim_list

        # Kapsadığı dönemlere göre ders baslangıc ve bitis tarihlerini
        # baz alarak kapsadığı her bir dönemin seçilen ayda hangi gün
        # aralıklarını kapsadığı bilgisini tuple olarak dondurur. Bir
        # dönemi kapsıyorsa bir tuple, iki dönemi kapsıyorsa iki tuple
        # döner. (4,12) (19,31) gibi

        tarih_araligi = donem_aralik_dondur(donem_list, yil, ay, takvim, akademik_takvim_list)

        self.output['objects'] = [['Okutman']]

        _form = JsonForm(current=self.current)

        kontrol = self.current.task_data["control"]
        if kontrol:
            _form.title = " %s Yılı %s Ayı Ders Ücreti Puantaj Tablosu" % (yil, ay_isim)
        else:
            _form.title = " %s Yılı %s Ayı Ek Ders Ücreti Puantaj Tablosu" % (yil, ay_isim)

        self.form_out(_form)

        for secilen_okutman in self.current.task_data["secilen_okutmanlar"]:
            okutman = Okutman.objects.get(secilen_okutman['key'])

            # Seçilen okutmanın İzin ve Ücretsiz İzinlerini dikkate alarak, verilen ayda
            # hangi günler izinli olduğunu liste halinde döndürmeye yarayan method
            # [17,18,19] gibi
            personel_izin_list = Izin.personel_izin_gunlerini_getir(okutman, yil, ay)

            okutman_adi = okutman.ad + ' ' + okutman.soyad

            # Verilen döneme ve okutmana göre, haftada hangi gün kaç saat dersi
            # (seçilen seçeneğe göre ders veya ek ders) olduğunu gösteren
            # dictionarylerden oluşan liste, seçilen yıl ve ay bir dönemi kapsıyorsa
            # bir dict, iki dönemi kapsıyorsa iki dict döner.
            ders_etkinlik_list = okutman_etkinlikleri_hesaplama(donem_list, okutman, kontrol)

            # Bulunan tarih araliklarina, okutmanın aylık ders etkinliklerine göre
            # ayın hangi gününde dersi varsa kaç saat dersi olduğu bilgisi,
            # izinliyse İ, resmi tatilse R bilgisini bir dictionary e doldurur.
            okutman_aylik_plan, ders_saati = ders_saati_doldur(donem_list, ders_etkinlik_list,
                                                               resmi_tatil_list, personel_izin_list,
                                                               tarih_araligi, yil, ay)

            data_list = OrderedDict({})
            data_list['Okutman'] = okutman_adi + "  " + str(ders_saati)
            item = {
                'type': "table-multiRow",
                'fields': data_list,
                'actions': False
            }
            self.output['objects'].append(item)


def ders_saati_doldur(donem_list, ders_etkinlik_list, resmi_tatil_list, personel_izin_list, tarih_araligi, yil, ay):
    ders_saati = 0
    okutman_aylik_plan = {}

    # Tarih aralığı bir tuple olduğu için
    # her bir dönem için o dönemin tarih aralığı
    # dikkate alınır.
    for j, donem in enumerate(donem_list):
        okutman_ders_dict = ders_etkinlik_list[j]

        for i in range(tarih_araligi[j][0], tarih_araligi[j][1] + 1):

            gun = calendar.weekday(yil, ay, i) + 1
            # calendar haftanın günlerini 0-6, biz 1-7
            # olarak aldığımız için 1 ile toplanıyor.

            # Eğer gün personel izin listesinde varsa
            if i in personel_izin_list:
                okutman_aylik_plan[i] = 'İ'

            # Eğer gün personel izin listesinde varsa
            elif i in resmi_tatil_list:
                okutman_aylik_plan[i] = 'R'

            # Eğer o gün izinli ya da resmi tatil değilse
            # ve dersi varsa dictin gün keyine kaç saat olduğu
            # value'su eklenir ve ders saati arttırılır.
            elif gun in okutman_ders_dict:
                okutman_aylik_plan[i] = okutman_ders_dict[gun]
                ders_saati += okutman_ders_dict[gun]

    return okutman_aylik_plan, ders_saati


def okutman_etkinlikleri_hesaplama(donem_list, okutman, kontrol):
    ders_etkinlik_list = []
    # kontrol ders ya da ek ders hesaplamasını gösterir.
    # Eğer kontrol True ise ders, False ise ek ders hesaplanır.

    # Verilen dönemde okutmanın hangi günler kaç saat dersi olduğu
    # bilgisini dict halinde döndürür. Günler 1-7 Pazt-Pazar
    # şeklinde belirlenmiştir. Örnek: {1:4, 3:3,4:2} gibi. Bu
    # dict bize okutmanın Pazartesi 4 saat, Çarşamba günü 3 saatlik
    # dersi olduğunu gösterir.
    for donem in donem_list:

        okutman_ders_dict = {}

        for etkinlik in DersEtkinligi.objects.filter(donem=donem, okutman=okutman, ek_ders=not kontrol):

            if not etkinlik.gun in okutman_ders_dict:
                okutman_ders_dict[etkinlik.gun] = etkinlik.sure
            else:
                okutman_ders_dict[etkinlik.gun] += etkinlik.sure

        ders_etkinlik_list.append(okutman_ders_dict)

    return ders_etkinlik_list


def donem_aralik_dondur(donem_list, yil, ay, takvim, akademik_takvim_list):
    tarih_araligi = []

    # Hangi dönemin ders başlangıç ve bitiş tarihini
    # dikkate almak için Akademik Takvim'de bulunan etkinlik
    # döneme göre seçilir.
    for j, donem in enumerate(donem_list):
        if 'Güz' in donem.ad:
            etkinlik = 66
        elif 'Bahar' in donem.ad:
            etkinlik = 67
        else:
            etkinlik = 68

        # Kapsanan donemin ders baslangic tarihi
        ders_bas_tarih = Takvim.objects.get(akademik_takvim=akademik_takvim_list[j],
                                            etkinlik=etkinlik).baslangic.date()

        # Kapsanan donemin ders bitis tarihi
        ders_bit_tarih = Takvim.objects.get(akademik_takvim=akademik_takvim_list[j],
                                            etkinlik=etkinlik).bitis.date()

        # Seçilen ayın ilk günü = 01.08.2016
        ay_baslangic = date(yil, ay, 01)

        # Seçilen ayın son günü = 31.08.2016
        ay_bitis = date(yil, ay, takvim[1])

        # 08.08.2016 > 01.08.2016
        # baslangic_tarih = 08.08.2016
        if ders_bas_tarih > ay_baslangic and ders_bas_tarih.month == ay:
            baslangic_tarih = ders_bas_tarih

        # 05.09.2016 > 01.08.2016
        # baslangic_tarih = 31.08.2016
        elif ders_bas_tarih > ay_baslangic and ders_bas_tarih.month != ay:
            baslangic_tarih = ay_bitis

        # 15.07.2016 < 01.08.2016
        # baslangic_tarih = 01.08.2016
        else:
            baslangic_tarih = ay_baslangic

        # 15.08.2016 < 31.08.2016
        # bitis_tarih = 15.08.2016
        if ders_bit_tarih < ay_bitis and ders_bit_tarih.month == ay:
            bitis_tarih = ders_bit_tarih

        # 25.07.2016 < 31.08.2016
        # bitis_tarih = 01.08.2016
        elif ders_bit_tarih < ay_bitis and ders_bit_tarih.month != ay:
            bitis_tarih = ay_baslangic

        # 15.09.2016 > 31.08.2016
        # bitis_tarih = 31.08.2016
        else:
            bitis_tarih = ay_bitis

        tarih_araligi.append((baslangic_tarih.day, bitis_tarih.day))

    return tarih_araligi


# donem getir (once olan)
# ders baslangic tarihi = haziran 3
# ders bitis tarihi = haziran 28
# haziran 1 - haziran 30 sorgu araligi
# haziran 1, ders baslangic tarihinden once mi? 'haziran 3' : 'haziran 1'
# kac donem var?
## 1
### ders bitis tariginden once mi? 'haziran 30': 'haziran 28'
### 1 donem, 3 haziran - 28 Haziran

## 2
### ders bitis tariginden once mi? 'haziran 30': 'haziran 28'
### 1 donem, 3 haziran - donem.ders bitis_tarihine kadar
### 2 donem, donem.ders_Baskangic - haziran 28 e kadar.

3 - 10, 17 - 28

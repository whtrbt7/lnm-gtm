# GTM Account Status

Live snapshot from Supabase. **517 accounts fully complete** (`script_injected`). Below: accounts needing action.

Last updated: 2026-05-11

---

## Status Definitions

| Status | Meaning | Next Step |
|---|---|---|
| `script_injected` | GTM snippet live on site. All tags/triggers configured. Done. | — |
| `configured` | Tags set up in GTM. Not yet published or injected. | Publish workspace → run `inject_wordpress.py` |
| `has_container` | GTM container created. Tags/triggers not configured. | Run `setup_tags.py` → publish → inject |
| `injection_failed` | Tags configured but WordPress injection failed. | Run `inject_wordpress.py --gads-cid CID` |
| `null` | Container created but status unknown or not set. | Verify in GTM UI → update Supabase manually |

---

## Needs Attention

### injection_failed (77) — Tags ready, WordPress inject failed

| GTM ID | Name | URL |
|---|---|---|
| GTM-KK99HM9Q | Accurate Auto & Tire Repair - Powered by Victory | myaccurateauto.com |
| GTM-W22CN5HR | Affordable Automotive | affordableautoservicecenter.com |
| GTM-WF8438S3 | All Season Auto & Tire | allseasontireco.com |
| GTM-N8RWVW83 | Amerifix - Franklin | amerifixfranklin.com |
| GTM-PX2TMWGJ | Arnie's Service Center | arniesservicecenter.com |
| GTM-TXJVQG6L | Arvalet Auto Center | arvalet.com |
| GTM-NJJMGJX3 | Auto Pro Shelby | autoproshelby.com |
| GTM-55CCHKBR | Auto Service Kingston | autoservicekingston.ca |
| GTM-TQ5SBBC9 | Bemer Plus | bemerplushouston.com |
| GTM-MDP84HZS | Ben Nielsen's 10th Street Automotive | 10thstreetautomotive.com |
| GTM-NCPSWQMR | Ben Nielsen's Alexandria Auto Care | alexandriaautocare.com |
| GTM-PMCQZKFR | Ben Nielsen's Skyline Automotive | skylineautomotive.net |
| GTM-KBPWLD3D | Ben Nielsen's Springfield Auto Care | springfieldautocare.com |
| GTM-PB2ZM2RK | Brown's Body Shop - Franklin | brownsbodyshopfranklin.com |
| GTM-KVMVHBCQ | Certified Auto Repair | certifiedautorva.com |
| GTM-WSNQBJQD | Checkpoint Motors | checkpointmotors.com |
| GTM-M9Q5K64M | Chuck's Auto Repair | chucksautocanton.com |
| GTM-MNV8LPQD | Delta V RVA | deltavrva.com |
| GTM-TB2QL7H8 | ELITE AUTO REPAIR | eliteauto.repair |
| GTM-NRNMZNKW | G & J Auto Repair Shop | gjautorepair.com |
| GTM-MTT6SLSK | Gibbs Automotive | gibbsautomotive.com |
| GTM-WC2JRHQK | GoodHart Motors | goodhartmotors.com |
| GTM-TKDGQWB7 | Guardian Automotive | guardianauto.ca |
| GTM-KTPGCZT8 | Integrity Collision | integritycollisionrepair.com |
| GTM-TDQX6XCQ | J&M Auto Service - Tea | jmtransmissionservice.com |
| GTM-NKN46KM2 | James Automotive | jamesautomotivespringfield.com |
| GTM-TBRXSSM6 | Joe Thurs Automotive | joethursautomotive.com |
| GTM-PW473L37 | John's Automotive Care | www.johnsautomotivecareelcajon.com |
| GTM-MKGQKFBJ | K O Autmotive | koautomotive1.com |
| GTM-WXXLCVH2 | Knight's Automotive | knightsautomotive.net |
| GTM-PX4357KP | Kwik Kar (Cedar Hill) | kwikkarcedarhill.com |
| GTM-M5DQLR27 | Mac's Radiator | auburnautoanalytx.com |
| GTM-MVZKVJH2 | Mac's Radiator - Beaverton | autoservicebeaverton.com |
| GTM-MWV9R9F8 | Maple Grove Auto Service | maplegroveauto.com |
| GTM-MPZS9TGL | Maysville Auto Repair | maysvilleautorepair.com |
| GTM-WTZG3RHL | Mechanics on Wheelz | mechanicsonwheelz.com |
| GTM-K2F9L8W9 | Michalak's Auto Repair - Souderton | soudertonautorepair.com |
| GTM-NKCM4L2 | Mike's Auto Service & Repair | mikesautoservicerepair.com |
| GTM-WS8JCN6W | Milex Mr. Transmission | milexcompleteautocare.com/florence-auto/ |
| GTM-KCQSD3QJ | Modern Automotive | mymodernautomotive.com |
| GTM-MGM6T6G5 | Northside Service of Altoona | northsideservicellc.com |
| GTM-W3JZVW27 | PW Auto Clinic Inc | pwautoclinic.com |
| GTM-P37CR93T | Precision Auto Solutions | precisionautosolutions.com |
| GTM-NQJQ8KT9 | Preferred Auto & Fleet Service | preferredauto.ca |
| GTM-NNTZR28D | RI Automotive | riautomotive.net |
| GTM-K5FGKMHJ | Redline Bimmer | redlinebimmer.com |
| GTM-W434PQRR | Rev-Up Auto (Carrollton) | rev-upauto.com |
| GTM-KNHCTPNJ | Revive Medical Center | rmcgeorgia.com |
| GTM-WC2W3RZH | Riverhill Automotive | riverhillautomotive.com |
| GTM-WCLLGDKS | SUPERIOR COLLISION OF EAGAN | superiorcollisionmn.com |
| GTM-PDW3Z8ZX | Speed Auto Repair - Jasper | speedjasper.com |
| GTM-M6K3LHSZ | Steger Service | stegerservice.com |
| GTM-MCQPDPVG | The Auto Experts - 30th Street | sacramentocarcare.com |
| GTM-P99TQ2PJ | The German Car Shoppe | thegermancarshoppe.com |
| GTM-KV6TNKB2 | Thomas Tuning and Service | ttsknoxville.com |
| GTM-KJ274NLP | Trinity Automotive and Transmission | trinityautomotivetx.com |
| GTM-5HZRKHQT | Victory Tire & Auto - Stillwater / Oak Park Heights | VictoryStillwaterMN.com |
| GTM-KPDH95KS | Victory Tire & Auto - Alexandria | victoryalexandria.com |
| GTM-THKPN572 | Victory Tire & Auto - Brooklyn Park W | victorybrooklynpark.com |
| GTM-PWGX67RF | Victory Tire & Auto - Buffalo | victoryautomotivebuffalomn.com |
| GTM-NGXB6F54 | Victory Tire & Auto - Burnsville | victoryautomotiveburnsville.com |
| GTM-TB2QMJNJ | Victory Tire & Auto - Chanhassen | VictoryChanhassen.com |
| GTM-5869B8FB | Victory Tire & Auto - Crosslake | victorycrosslake.com |
| GTM-TZ4295R8 | Victory Tire & Auto - Eau Claire | victoryautoeauclaire.com |
| GTM-WK4SMGST | Victory Tire & Auto - Fridley | victoryfridley.com |
| GTM-KMSSZ3H3 | Victory Tire & Auto - Grand Rapids W | victorygrandrapidswest.com |
| GTM-PRX3DKPL | Victory Tire & Auto - Granite City | victorygranitecity.com |
| GTM-T8CKQFMG | Victory Tire & Auto - Ham Lake | victoryhamlake.com |
| GTM-KRVNM69V | Victory Tire & Auto - Maplewood | victoryautoservicemaplewood.com |
| GTM-MJBFGKF8 | Victory Tire & Auto - St. Petersburg | victoryautostpete.com |
| GTM-TSGC225T | Victory Tire & Auto - White Bear Lake | VictoryWhiteBearLake.com |
| GTM-KKW9LVCG | Victory Tire & Auto - Wyoming | VictoryWyomingMN.com |
| GTM-MXXHBP3M | Victory Tire & Auto - Brooklyn Park E | victorybrooklynparkeast.com |
| GTM-TT4G9TCH | Village Autoworks | villageautoworks.com |
| GTM-NTFCVPXD | Warzecha Tire & Auto - Powered by Victory - Zimmerman | warzechatireandauto.com |
| GTM-PDKKM6ML | Western Auto Service | westernautoboise.com |
| GTM-5JK2S72M | Zima Automotive | zimaautomotive.com |

---

### has_container (18) — Container created, tags not configured

| GTM ID | Name | URL |
|---|---|---|
| GTM-WFMBGKRR | All Season Collision | allseasoncollision.com |
| GTM-MK9TKZXH | Automotive Solutions (Brand) | automotivesolutionsmi.com |
| GTM-PJW3F7C6 | Blue Canary - Bainbridge Island | bluecanaryauto.com |
| GTM-P5CJ54SP | Carrigan Auto Group | carriganautogroup.com |
| GTM-5D3VCGNC | En-Tire Car Care Center | en-tire.com |
| GTM-P3KC63PV | Gales Detailing | galesdetailing.com |
| GTM-WGX47KPH | JTR Repair - Crawfordsville | jtrrepair.com |
| GTM-M9HXWLP5 | Journey Auto Repair | journeyautorepair.com |
| GTM-MS3XR82Q | Lanier Auto Repair and Tire | lanierautokennesaw.com |
| GTM-565VGR4H | M&M Car Care Center - Dyer | dyerautorepair.com |
| GTM-PSDBXG55 | M&M Car Care Center - Hobart | mmcarcarehobart.com |
| GTM-WH9978HX | M&M Car Care Center - Merillville | autorepairmerrillville.com |
| GTM-K9DTVS74 | Olson Auto | olsonautollc.com |
| GTM-PGRS7H9W | Saginaw Dixie Hwy | servicecentersaginaw.com |
| GTM-NVCVC4LV | Saginaw State Street | autorepairsaginaw.com |
| GTM-KSPS6B6Q | Sculley's Automotive (S Main) | sculleysautomotive.com |
| GTM-KK9LPX7K | Skiles Automotive Services - Southbend | autorepairsouthbend.com |
| GTM-P6RR7WJX | Town Center Automotive | towncenter-automotive.com |

---

### null status (12) — Status unknown, needs manual verify

| GTM ID | Name | URL |
|---|---|---|
| — | AWD Auto - Bothell Everett Hwy | driveautosports.com |
| — | AWD Auto - NE Kirkland | driveautosports.com |
| GTM-P9XZRSCX | Breeze Brakes Auto | breezebrakes.com |
| GTM-KP4KX27K | Chesterland Auto Repair | chesterlandautorepair.com |
| GTM-5QLDKZC4 | Chris Matthews Automotive | chrismatthewsauto.com |
| GTM-TVWVQ8QT | Doc Auto Care - Warrenton | fredericksburgautorepair.com |
| GTM-5VHBGMLR | Linville Brothers | linvillebrothers.com |
| GTM-PBC47S9Q | Park Cities Auto Care | parkcitiesautocare.com |
| GTM-MXFPJSR4 | Prairie Road Automotive | prairieroadautomotive.com |
| GTM-KFBD8WDQ | Q Star Auto Repair | qstarautorepairs.com |
| GTM-5JX3C546 | Route 11 Auto Repair - New Market | autorepairnewmarketva.com |
| GTM-PPFHVZTL | TechPoint Auto Solutions - Jonestown | techpointautosolutions.com |

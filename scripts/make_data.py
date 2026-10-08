"""Generate the SYNTHETIC dataset used by the demo and evals. No real households.
Deterministic: running it twice gives identical files."""
import csv, json, pathlib
D = pathlib.Path(__file__).resolve().parent.parent / "data"
D.mkdir(exist_ok=True)

# --- households: deliberately messy (mixed units, missing size, missing phone, duplicate) ---
H = [
 # id, collective, ward, station, zone, crop, soil, size, unit, stage, planted, stock_bags, seed_in_stock, phone, channel, yields, dup_of
 ("HH-001","KAV-A","Kavuli","ST-KAV","Z1","maize","loam","1.5","acre","none","",0,"yes","+254700000001","sms","820;640;710",""),
 ("HH-002","KAV-A","Kavuli","ST-KAV","Z1","maize","sandy","0.75","acre","none","",0,"no","+254700000002","sms","410;380;",""),
 ("HH-003","KAV-A","Kavuli","ST-KAV","Z1","maize","loam","1","acre","emergence","2026-09-25",0,"yes","+254700000003","sms","900;760;850",""),
 ("HH-004","KAV-A","Kavuli","ST-KAV","Z1","sorghum","clay","2","ha","none","",0,"yes","+254700000004","ussd","600;590;640",""),
 ("HH-005","KAV-A","Kavuli","ST-KAV","Z1","maize","loam","1","acre","none","",6,"yes","","visit","7 bags;5 bags;6 bags",""),
 ("HH-006","MUT-B","Muthini","ST-MUT","Z1","maize","loam","1","acre","none","",0,"yes","+254700000006","sms","700;650;690",""),
 ("HH-007","MUT-B","Muthini","ST-MUT","Z1","beans","clay","","","none","",0,"yes","+254700000007","sms","250;;230",""),
 ("HH-008","MUT-B","Muthini","ST-MUT","Z1","maize","loam","1","acre","none","",0,"yes","+254700000008","sms","700;650;690","HH-006"),
 ("HH-009","MUT-B","Muthini","ST-MUT","Z1","sorghum","sandy","1.25","acre","none","",0,"no","+254700000009","ussd","450;500;480",""),
 ("HH-010","NDU-C","Nduu","","Z2","maize","clay","2","acre","none","",0,"yes","+254700000010","sms","950;870;920",""),
 ("HH-011","NDU-C","Nduu","","Z2","beans","loam","0.5","acre","none","",0,"no","+254700000011","sms","300;280;310",""),
 ("HH-012","NDU-C","Nduu","","Z2","maize","loam","1.5","acre","none","",0,"yes","+254700000012","ussd","880;;900",""),
]
cols = ["household_id","collective_id","ward","station_id","zone_id","crop","soil","plot_size","plot_unit",
        "crop_stage","planted_date","stored_bags","seed_in_stock","phone","channel","yield_history","possible_duplicate_of"]
with open(D/"households.csv","w",newline="") as f:
    w = csv.writer(f); w.writerow(cols); w.writerows(H)

# --- rainfall, dekadal mm (SYNTHETIC, CHIRPS-like shape). ST-MUT is missing the 2026-09-21 dekad. ST-NDU has no data at all. ---
dekads = ["2026-08-01","2026-08-11","2026-08-21","2026-09-01","2026-09-11","2026-09-21","2026-10-01"]
rain = {"ST-KAV":[2,0,1,4,12,18,31], "ST-MUT":[3,2,0,1,5,None,22]}
with open(D/"rainfall.csv","w",newline="") as f:
    w = csv.writer(f); w.writerow(["station_id","dekad_start","mm","provisional"])
    for st,vals in rain.items():
        for d,v in zip(dekads,vals):
            w.writerow([st,d,"" if v is None else v,"yes" if d=="2026-10-01" else "no"])

json.dump({
 "stations":{"ST-KAV":{"zone":"Z1","name":"Kavuli (synthetic)"},"ST-MUT":{"zone":"Z1","name":"Muthini (synthetic)"}},
 "nearest_station":{"Nduu":{"station":"ST-KAV","distance_km":18}},
 "outlooks":{
   "Z1":{"source_id":"OUT-2026-OND-Z1","season":"OND 2026","above":0.25,"normal":0.35,"below":0.40,"note":"synthetic outlook"},
   "Z2":{"source_id":"OUT-2026-OND-Z2","season":"OND 2026","above":0.35,"normal":0.40,"below":0.25,"note":"synthetic outlook"}}
}, open(D/"stations.json","w"), indent=1)

json.dump([
 {"alert_id":"PA-2026-0931","ward":"Kavuli","pest":"fall armyworm","crop":"maize","reported":"2026-10-03","status":"officer-verified","channel":"county pest WhatsApp group"},
 {"alert_id":"PA-2026-0870","ward":"Muthini","pest":"stem borer","crop":"maize","reported":"2026-08-20","status":"unverified","channel":"county pest WhatsApp group"},
], open(D/"pest_alerts.json","w"), indent=1)

# --- market prices, KES per 90kg bag maize (SYNTHETIC). M-WAN 2026-W39 maize is an obvious entry error (outlier). ---
P = [("M-KAV","maize","2026-W36",3900),("M-KAV","maize","2026-W37",4000),("M-KAV","maize","2026-W38",4100),("M-KAV","maize","2026-W39",4300),
     ("M-WAN","maize","2026-W36",3800),("M-WAN","maize","2026-W37",3850),("M-WAN","maize","2026-W38",3950),("M-WAN","maize","2026-W39",9800),
     ("M-TWN","maize","2026-W36",3700),("M-TWN","maize","2026-W37",3750),("M-TWN","maize","2026-W38",3900),("M-TWN","maize","2026-W39",4050),
     ("M-KAV","beans","2026-W39",11000),("M-TWN","beans","2026-W39",11500)]
with open(D/"prices.csv","w",newline="") as f:
    w = csv.writer(f); w.writerow(["market_id","crop","week","price_kes_per_90kg"]); w.writerows(P)

json.dump({"as_of":"2026-10-07","synthetic":True,
 "note":"All records are synthetic. No real household, plot, or price is represented."}, open(D/"meta.json","w"), indent=1)
print("data written to", D)

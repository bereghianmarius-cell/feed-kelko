import pandas as pd

# 1. Carica il file CSV sorgente
df = pd.read_csv('tuo_file_sorgente.csv', sep='|')

shopify_rows = []

# 2. Scorre ogni riga del file direttamente
for idx, row in df.iterrows():
    sku = str(row['SKU']).strip()
    size = row.get('MODEL_SIZE', '')
    
    # Costruisce lo SKU della variante unendo SKU e Taglia (se presente)
    sku_var = f"{sku}_{size}" if pd.notna(size) and str(size).strip() != '' else sku
    
    # Calcolo prezzo con ricarico del 70% (+70%)
    price_val = float(row['PRICE']) if pd.notna(row['PRICE']) else 0.0
    price_markup = round(price_val * 1.70, 2)
    
    compare_price = round(float(row['STREET_PRICE']), 2) if pd.notna(row['STREET_PRICE']) else ""
    qty = int(row['QUANTITY']) if pd.notna(row['QUANTITY']) else 0
    
    # --- LETTURA EAN / BARCODE DIRETTA ---
    raw_barcode = row.get('BARCODE', row.get('EAN', ''))
    if pd.notna(raw_barcode) and str(raw_barcode).strip() != '':
        barcode = str(raw_barcode).split('.')[0].strip() # Pulisce eventuali decimali .0
    else:
        barcode = ""
    
    # Gestione immagini
    images = [row.get('PICTURE_1', ''), row.get('PICTURE_2', ''), row.get('PICTURE_3', '')]
    images = [img for img in images if pd.notna(img) and str(img).strip() != '']
    
    # Mappatura per il formato Shopify
    shopify_row = {
        'Handle': sku.lower().replace('_', '-').replace(' ', '-'),
        'Title': row.get('Titel_ITA', ''),
        'Body (HTML)': row.get('Description_ITA', ''),
        'Vendor': row.get('BRAND', ''),
        'Standard Product Type': row.get('SUBCAT', ''),
        'Custom Product Type': row.get('SUBCAT', ''),
        'Tags': f"{row.get('CAT', '')}, {row.get('SEX', '')}",
        'Published': 'TRUE',
        'Option1 Name': 'Taglia' if pd.notna(size) and str(size).strip() != '' else '',
        'Option1 Value': size if pd.notna(size) else '',
        'Option2 Name': 'Colore' if pd.notna(row.get('COLOR')) else '',
        'Option2 Value': row.get('COLOR', '') if pd.notna(row.get('COLOR')) else '',
        'Variant SKU': sku_var,
        'Variant Grams': 0,
        'Variant Inventory Tracker': 'shopify',
        'Variant Qty': qty,
        'Variant Inventory Policy': 'deny',
        'Variant Fulfillment Service': 'manual',
        'Variant Price': price_markup,
        'Variant Compare At Price': compare_price,
        'Variant Requires Shipping': 'TRUE',
        'Variant Taxable': 'TRUE',
        'Variant Barcode': barcode,  # <-- Qui viene inserito correttamente l'EAN
        'Image Src': images[0] if len(images) > 0 else '',
        'Image Position': 1 if len(images) > 0 else '',
        'Status': 'active'
    }
    shopify_rows.append(shopify_row)

# 3. Salva il file CSV finale formattato per Shopify
shopify_df = pd.DataFrame(shopify_rows)
shopify_df.to_csv('shopify_import_prodotti.csv', index=False, encoding='utf-8-sig')
print("File Shopify generato con successo con i codici EAN/Barcode inclusi!")

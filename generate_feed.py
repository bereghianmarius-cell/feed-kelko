def generate_kelkoo_xml(products):
    root = ET.Element("products")

    for prod in products:
        prod_title = str(prod.get("title", "")).strip().replace("?", "")
        handle = prod.get("handle", "")
        vendor = str(prod.get("vendor", "")).strip()
        category = str(prod.get("productType", "")).strip() or "General"
        
        main_img = prod.get("featuredImage", {}).get("url") if prod.get("featuredImage") else ""

        for var in prod.get("variants", {}).get("nodes", []):
            raw_var_id = str(var.get("id", "")).split("/")[-1]
            offer_id = str(var.get("sku") or raw_var_id).strip().replace("?", "")
            var_title = str(var.get("title", "")).strip().replace("?", "")
            
            # Titolo pulito
            if var_title and var_title.lower() != "default title":
                full_title = f"{prod_title} - {var_title}"
            else:
                full_title = prod_title
            
            # URL Prodotto
            product_url = f"https://{PUBLIC_DOMAIN}/products/{handle}?variant={raw_var_id}"
            
            price = str(var.get("price", "0.00")).strip()
            availability = "1" if var.get("availableForSale") else "2"
            
            var_img = var.get("image", {}).get("url") if var.get("image") else ""
            img_url = var_img or main_img
            
            if not img_url:
                continue

            # Pulizia rigorosa EAN
            ean_code = clean_ean(var.get("barcode"))

            # Costruzione nodo XML
            p_elem = ET.SubElement(root, "product")
            
            ET.SubElement(p_elem, "offer_id").text = offer_id
            ET.SubElement(p_elem, "title").text = full_title
            ET.SubElement(p_elem, "product_url").text = product_url
            ET.SubElement(p_elem, "price").text = price
            ET.SubElement(p_elem, "brand").text = vendor
            ET.SubElement(p_elem, "category").text = category
            ET.SubElement(p_elem, "availability").text = availability
            
            # Scrive il tag EAN solo se esiste davvero un codice numerico valido
            if ean_code and len(ean_code) > 3:
                ET.SubElement(p_elem, "ean").text = ean_code
                
            ET.SubElement(p_elem, "image_url").text = img_url

    xml_str = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(indent="  ")
    with open("kelkoo.xml", "w", encoding="utf-8") as f:
        f.write(xml_str)
    print("File kelkoo.xml generato perfettamente!")

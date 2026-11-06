import os
import requests
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Configurazione variabili d'ambiente
SHOP_URL = os.environ.get("SHOP_URL", "").replace("https://", "").replace("http://", "").strip("/")
CLIENT_ID = os.environ.get("CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "").strip()

# Dominio pubblico finale richiesto da Kelkoo
PUBLIC_DOMAIN = "25thstreet.it"

def get_access_token():
    url = f"https://{SHOP_URL}/admin/oauth/access_token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json()["access_token"]

def clean_ean(barcode):
    """Pulisce il codice EAN evitando format float o scientifici."""
    if not barcode:
        return ""
    barcode_str = str(barcode).strip()
    if barcode_str.endswith('.0'):
        barcode_str = barcode_str[:-2]
    cleaned = ''.join(filter(str.isdigit, barcode_str))
    return cleaned

def fetch_all_products(access_token):
    graphql_url = f"https://{SHOP_URL}/admin/api/2024-01/graphql.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": access_token
    }

    # Query con status:ACTIVE per prendere solo i prodotti attivi e visibili nel negozio
    query = """
    query getProducts($cursor: String) {
      products(first: 25, after: $cursor, query: "status:ACTIVE") {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          title
          handle
          vendor
          productType
          featuredImage {
            url
          }
          variants(first: 100) {
            nodes {
              id
              title
              sku
              price
              barcode
              availableForSale
              image {
                url
              }
            }
          }
        }
      }
    }
    """

    products = []
    cursor = None
    has_next_page = True

    while has_next_page:
        variables = {"cursor": cursor} if cursor else {}
        response = requests.post(graphql_url, json={'query': query, 'variables': variables}, headers=headers)
        
        if response.status_code != 200:
            print(f"Errore GraphQL: {response.text}")
            break

        data = response.json()
        if "errors" in data:
            print(f"Errore query: {data['errors']}")
            break

        product_data = data['data']['products']
        products.extend(product_data['nodes'])
        has_next_page = product_data['pageInfo']['hasNextPage']
        cursor = product_data['pageInfo']['endCursor']
        print(f"Scaricati {len(products)} prodotti attivi...")

    return products

def generate_kelkoo_xml(products):
    root = ET.Element("products")

    for prod in products:
        prod_title = prod.get("title", "")
        handle = prod.get("handle", "")
        vendor = prod.get("vendor", "")
        category = prod.get("productType", "") or "General"
        
        main_img = prod.get("featuredImage", {}).get("url") if prod.get("featuredImage") else ""

        for var in prod.get("variants", {}).get("nodes", []):
            raw_var_id = var.get("id", "").split("/")[-1]
            offer_id = var.get("sku") or raw_var_id
            var_title = var.get("title", "")
            
            full_title = f"{prod_title} - {var_title}" if var_title and var_title.lower() != "default title" else prod_title
            
            # URL Prodotto valido usando handle e ID variante per Shopify
            product_url = f"https://{PUBLIC_DOMAIN}/products/{handle}?variant={raw_var_id}"
            
            # Prezzo originale esatto da Shopify (nessun ricarico)
            price = str(var.get("price", "0.00"))
            
            availability = "1" if var.get("availableForSale") else "2"
            
            var_img = var.get("image", {}).get("url") if var.get("image") else ""
            img_url = var_img or main_img
            
            if not img_url:
                continue

            ean_code = clean_ean(var.get("barcode"))

            p_elem = ET.SubElement(root, "product")
            
            ET.SubElement(p_elem, "offer_id").text = str(offer_id)
            ET.SubElement(p_elem, "title").text = full_title
            ET.SubElement(p_elem, "product_url").text = product_url
            ET.SubElement(p_elem, "price").text = price
            ET.SubElement(p_elem, "brand").text = vendor
            ET.SubElement(p_elem, "category").text = category
            ET.SubElement(p_elem, "availability").text = availability
            
            if ean_code:
                ET.SubElement(p_elem, "ean").text = ean_code
            else:
                ET.SubElement(p_elem, "ean")
                
            ET.SubElement(p_elem, "image_url").text = img_url

    xml_str = minidom.parseString(ET.tostring(root, encoding="utf-8")).toprettyxml(indent="  ")
    with open("kelkoo.xml", "w", encoding="utf-8") as f:
        f.write(xml_str)
    print("File kelkoo.xml generato con successo!")

if __name__ == "__main__":
    token = get_access_token()
    prods = fetch_all_products(token)
    generate_kelkoo_xml(prods)

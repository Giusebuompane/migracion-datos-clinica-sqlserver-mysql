import csv
from pathlib import Path

from step02_db import get_connection

ENTITY_KEY = "mapping_products"

VOUCHER_TYPES = (2, 7, 5, 8, 9, 10, 11, 12)


def ensure_output_dir() -> Path:
    """
    output debe ir en ../output (relativo al script).
    """
    base_dir = Path(__file__).resolve().parent
    out_dir = base_dir.parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def run():
    conn = get_connection()
    cursor = conn.cursor()

    out_dir = ensure_output_dir()
    ambiguous_csv_path = out_dir / "bonos_ambiguos.csv"

    try:
        print(f"🔵 STEP → BUILD {ENTITY_KEY}")
        print("=" * 70)

        # 1) Crear tabla destino si no existe
        print("   [mapping_products] Creando tabla __mapping_products si no existe...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS `__mapping_products` (
                `id` INT(11) NOT NULL,
                `idFlowww` INT(11) NULL DEFAULT NULL,
                PRIMARY KEY (`id`)
            )
            ENGINE=MyISAM;
            """
        )
        conn.commit()
        
        # Limpiar tabla antes de reprocesar
        cursor.execute("DELETE FROM `__mapping_products`")
        conn.commit()

        # 2) Pre-check total services
        cursor.execute("SELECT COUNT(*) FROM __mapping_services;")
        total_services = cursor.fetchone()[0] or 0
        print(f"   [mapping_products] Filas en __mapping_services: {total_services}")
        if total_services == 0:
            raise RuntimeError("No hay filas en __mapping_services.")

        # 3) Construimos un result set con:
        #    - cnt = nº de DISTINCT xp.ProductID encontrados por cada ms.id
        #    - min_voucher = MIN(xp.ProductID) (solo útil cuando cnt=1)
        #    - lista de vouchers para auditoría
        print("   [mapping_products] Calculando correspondencias (y detectando ambiguos)...")
        cursor.execute(
            f"""
            SELECT
                ms.id                                 AS MappingID,
                ms.idFlowww                           AS BaseProductID,
                xpp.ProductDesc                       AS BaseProductDesc,
                COUNT(DISTINCT xp.ProductID)          AS MatchCount,
                MIN(xp.ProductID)                     AS VoucherProductID,
                GROUP_CONCAT(DISTINCT xp.ProductID ORDER BY xp.ProductID)  AS VoucherProductIDs,
                GROUP_CONCAT(DISTINCT xp.ProductDesc ORDER BY xp.ProductID SEPARATOR ' | ') AS VoucherProductDescs
            FROM __mapping_services ms
            INNER JOIN x_config_products_det xpp
                ON xpp.ProductID = ms.idFlowww
               AND xpp.ProductType IN (1,4)
            INNER JOIN x_config_products_det xp
                ON xpp.ProductID = xp.ProductVoucherPID
               AND xp.ProductVoucherNum = 1
               AND xp.ProductType IN ({",".join(str(x) for x in VOUCHER_TYPES)})
            INNER JOIN x_config_clinics xc
                ON xc.ClinicProductGID = xpp.ProductGID
            WHERE
                ms.idFlowww IS NOT NULL
            GROUP BY
                ms.id, ms.idFlowww, xpp.ProductDesc
            ;
            """
        )
        rows = cursor.fetchall()

        if not rows:
            raise RuntimeError(
                "No se han encontrado correspondencias con la query buena. "
                "Revisa ProductVoucherNum=1, ProductType o join con clinics."
            )

        # Columnas según SELECT
        # 0 MappingID
        # 1 BaseProductID
        # 2 BaseProductDesc
        # 3 MatchCount
        # 4 VoucherProductID
        # 5 VoucherProductIDs
        # 6 VoucherProductDescs

        ok_count = 0
        ambiguous_rows = []
        zero_count = 0  # (no debería pasar por el INNER JOIN, pero lo dejamos por robustez)

        for r in rows:
            match_count = int(r[3] or 0)
            if match_count == 1:
                ok_count += 1
            elif match_count > 1:
                ambiguous_rows.append(r)
            else:
                zero_count += 1

        print(f"   [mapping_products] OK (1 match): {ok_count}")
        print(f"   [mapping_products] Ambiguos (>1 match): {len(ambiguous_rows)}")
        if zero_count:
            print(f"   [mapping_products] Sin match: {zero_count}")

        # 4) Insertar los bonos mapeados en __mapping_products
        print("   [mapping_products] Guardando mapeos en __mapping_products...")
        cursor.execute(
            """
            REPLACE INTO __mapping_products (id, idFlowww)
            SELECT
                ms.id,
                xpv.ProductSourceID AS VoucherProductID
            FROM __mapping_services ms
                INNER JOIN x_config_products_det xpp ON xpp.ProductSourceID = ms.idFlowww AND xpp.ProductType IN (1,4) AND xpp.ProductSourceID=xpp.ProductID
                INNER JOIN x_config_products_det xpv ON xpv.ProductVoucherPID = xpp.ProductID AND xpv.ProductVoucherNum = 1 AND xpv.ProductType IN (2,5,9)
            ;
            """
        )
        conn.commit()

        # 5) Para ambiguos, dejamos idFlowww=NULL para evitar mapeo incorrecto (seguro)
        if ambiguous_rows:
            print("   [mapping_products] Anulando mapeo para IDs ambiguos (idFlowww=NULL)...")
            cursor.execute(
                f"""
                REPLACE INTO __mapping_products (id, idFlowww)
                SELECT
                    ms.id,
                    NULL
                FROM __mapping_services ms
                INNER JOIN x_config_products_det xpp
                    ON xpp.ProductID = ms.idFlowww
                   AND xpp.ProductType IN (1,4)
                INNER JOIN x_config_products_det xp
                    ON xpp.ProductID = xp.ProductVoucherPID
                   AND xp.ProductVoucherNum = 1
                   AND xp.ProductType IN ({",".join(str(x) for x in VOUCHER_TYPES)})
                INNER JOIN x_config_clinics xc
                    ON xc.ClinicProductGID = xpp.ProductGID
                WHERE
                    ms.idFlowww IS NOT NULL
                GROUP BY
                    ms.id
                HAVING
                    COUNT(DISTINCT xp.ProductID) > 1
                ;
                """
            )
            conn.commit()

        # 6) Export ambiguos a CSV
        if ambiguous_rows:
            print("⚠️  [mapping_products] ADVERTENCIA: Se han detectado bonos ambiguos.")
            print(f"⚠️  [mapping_products] Generando CSV: {ambiguous_csv_path}")

            with open(ambiguous_csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow([
                    "MappingID",
                    "BaseProductID",
                    "BaseProductDesc",
                    "MatchCount",
                    "VoucherProductIDs",
                    "VoucherProductDescs",
                ])
                for r in ambiguous_rows:
                    w.writerow([
                        r[0],
                        r[1],
                        r[2],
                        r[3],
                        r[5],
                        r[6],
                    ])

            print("⚠️  [mapping_products] Revisar con Flowww cuál es el bono correcto. (bonos_ambiguos.csv)")

        # 7) Log final
        cursor.execute("SELECT COUNT(*) FROM __mapping_products;")
        total_products = cursor.fetchone()[0] or 0
        print(f"   [mapping_products] Filas en __mapping_products: {total_products}")
        print("✅ OK: __mapping_products generado/actualizado.")

        return {
            "status": "ok",
            "rows_services": total_services,
            "ok_mappings": ok_count,
            "ambiguous": len(ambiguous_rows),
            "output_csv": str(ambiguous_csv_path) if ambiguous_rows else None,
        }

    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    run()

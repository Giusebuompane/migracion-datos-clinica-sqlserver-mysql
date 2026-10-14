import mysql.connector
from step01_config import MYSQL_CONFIG, SESSION_SQL_INIT

def ejecutar_migracion():
    conn = None
    try:
        # 1. Conexión a la base de datos usando el diccionario de tu config
        conn = mysql.connector.connect(
            host=MYSQL_CONFIG['host'],
            user=MYSQL_CONFIG['user'],
            password=MYSQL_CONFIG['password'],
            database=MYSQL_CONFIG['database'],
            port=MYSQL_CONFIG['port'],
            charset=MYSQL_CONFIG['charset']
        )
        
        cursor = conn.cursor()

        # 2. Inicializar sesión (opcional, según tu config)
        cursor.execute(SESSION_SQL_INIT)

        # 3. Ejecutar las queries
        # Nota: Ejecutamos una por una porque mysql-connector no permite múltiples 
        # sentencias en un solo execute() por seguridad a menos que se especifique.
        
        # Preparar variables
        cursor.execute("SET @NextProductID=IFNULL((SELECT MAX(ProductID) FROM x_config_products_det),0)+1;")
        cursor.execute("SET @MigradoExists=IFNULL((SELECT ProductID FROM x_config_products_det WHERE ProductDesc='Migrado' LIMIT 1),0);")
        
        # Insertar si no existe
        cursor.execute("""
            INSERT INTO `x_config_products_det` 
            (`ProductID`,`ProductParentID`,`ProductSourceID`,`ProductGID`,`ProductFamilyID`,`ProductZoneClassID`,`ProductZoneCode`,`ProductDesc`,`ProductType`,`ProductDisabled`)
            SELECT @NextProductID,@NextProductID,@NextProductID,0,0,0,'MGRD','Migrado',4,-1 
            WHERE @MigradoExists=0;
        """)
        
        # Confirmar cambios (importante ya que autocommit está en False en tu config)
        conn.commit()

        # 4. Obtener el ID resultante
        cursor.execute("SELECT IF(@MigradoExists!=0,@MigradoExists,@NextProductID) AS MigratedProductID;")
        resultado = cursor.fetchone()

        if resultado:
            print("\n" + "="*30)
            print(f"ID DE PRODUCTO MIGRADO: {resultado[0]}")
            print("="*30 + "\n")
        else:
            print("No se pudo obtener el ID.")

    except mysql.connector.Error as err:
        print(f"Error de base de datos: {err}")
    except Exception as e:
        print(f"Error inesperado: {e}")
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

if __name__ == "__main__":
    ejecutar_migracion()
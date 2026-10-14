# Migración de datos de una clínica: de SQL Server a Flowww (MySQL)

Este repositorio recoge la migración completa de los datos de una clínica de medicina estética desde su antiguo software de gestión (base de datos SQL Server) a Flowww, un ERP en la nube para clínicas que trabaja sobre MySQL. Hice el proyecto entero en mi trabajo en EVOTIC: el análisis del origen, la extracción, la transformación a las plantillas de Flowww, la carga en la base de datos de producción y la migración de los ficheros físicos (documentos y fotos).

Por privacidad he anonimizado el nombre de la clínica y he quitado todo lo que pudiera identificar a pacientes o servidores. En el repositorio solo hay código: ningún dato real.

## Contexto

La clínica me entregó una copia de seguridad (`.bak`) de su base de datos y una exportación con todos sus ficheros: consentimientos firmados, informes en PDF y fotos de tratamientos. El objetivo era que el primer día de trabajo con Flowww tuvieran disponible todo su histórico: fichas de clientes, historia clínica, agenda, presupuestos, deudas pendientes, anticipos, estudios antropométricos, documentos y fotos.

El origen y el destino no se parecen en nada. El software antiguo guarda a todas las personas (clientes, empleados, profesionales) en una misma tabla, calcula las deudas al vuelo con procedimientos almacenados y relaciona los ficheros con los clientes por rutas de carpeta. Flowww espera una tabla por concepto, con sus propios identificadores y catálogos (tarifas, usuarios, cabinas), así que buena parte del trabajo fue entender bien el modelo de origen antes de escribir una sola línea de transformación.

## Herramientas

- **SQL Server / T-SQL** (SSMS): restauración del `.bak`, análisis del modelo y creación de vistas y tablas auxiliares.
- **Python** (pandas, SQLAlchemy, pyodbc): extracción, limpieza y generación de los CSV en el formato de Flowww.
- **Jupyter Notebook**: un bloque por tabla, documentado con celdas de texto, para poder repetir cualquier paso por separado.
- **MySQL** (mysql-connector-python): carga en la base de datos de Flowww mediante tablas de staging.
- **PowerShell**: copia de los documentos y conversión de las fotos en el servidor de destino.

## Estructura del repositorio

```
.
├── 01_extraccion/
│   ├── sql/                         Vistas y tablas auxiliares en SQL Server
│   └── notebooks/
│       ├── 01_generacion_csv.ipynb              Genera un CSV por tabla de Flowww
│       ├── 02_correccion_rutas_ficheros.ipynb   Cuadra files/pictures con los ficheros físicos
│       └── historico/                           Primera versión, con pruebas que luego descarté
├── 02_carga/
│   ├── orchestrator.py              Ejecuta la carga completa en orden
│   ├── step01_config.py             Conexión, contexto y entidades activas
│   ├── obtener_id.py                Crea o recupera el producto genérico "Migrado"
│   └── scripts/                     Un loader por entidad + conexión, reset y backup
├── Libs/
│   └── flowww_utils.py              Funciones de limpieza y normalización reutilizables
├── .env.example
└── requirements.txt
```

## El proceso

### 1. Restaurar y entender el origen

Restauré el `.bak` en un SQL Server local y dediqué la primera fase a consultar el modelo: qué tablas tenían datos, cómo se relacionaban y qué significaba cada campo. Los scripts de esta parte están en `01_extraccion/sql/consultas_tablas.sql`.

Lo más importante que saqué de este análisis:

- Todas las personas están en la tabla `persona`, identificadas por un GUID (`codpersona`). Flowww necesita un identificador numérico, así que creé una copia de la tabla (`person_dup`) con una columna autonumérica `personaID`. Ese ID es el que uso después en todas las tablas para enlazar cada registro con su cliente.
- Había muchos registros sin nombre o sin apellido y bastantes duplicados por nombre completo, así que los revisé antes de decidir qué se migraba.
- Las deudas y los anticipos no existen como tabla: el programa los calcula con los procedimientos almacenados `ObtenerDeudoresAcreedoresAFechaActual` y `ObtenerDeudoresAcreedoresAFinDeAnyo`. Para poder migrarlos ejecuté esos procedimientos y guardé el resultado en dos tablas físicas, `deudores` y `acreedores`.

### 2. Preparar el origen en SQL Server

En lugar de hacer todas las transformaciones en Python, dejé en SQL Server vistas que ya devuelven los datos con la forma más parecida posible a lo que pide Flowww. Así cada consulta se puede revisar en SSMS y el notebook solo se ocupa de limpiar y dar formato.

| Script | Qué prepara |
|---|---|
| `tabla_clients_diary_gen_script_completo.sql` | `person_dup` y la vista `clients`; la agenda futura |
| `tabla_budgets_gen_script_completo.sql` | `product_map` (catálogo de tratamientos con ID numérico), `budget_map` y la vista `budgets_gen` |
| `creacion_tabla_deudores.sql` / `create_table_acreedores.sql` | Tablas físicas de deudas y anticipos a partir de los procedimientos almacenados |
| `create_vista_parametros_corporales.sql` | Vista con las mediciones de los estudios antropométricos |
| `tabla_files_path.sql` | Relación entre la tabla `multimedia` y la carpeta de cada cliente |

Los scripts principales borran primero lo que crean, así que se pueden ejecutar varias veces. Me hizo falta, porque repetí la preparación cada vez que llegaba una copia nueva de la base de datos.

### 3. Generar los CSV con Python

El notebook `01_generacion_csv.ipynb` tiene un bloque por cada tabla de destino. Cada bloque se conecta a SQL Server con autenticación de Windows, lee su vista, limpia los datos y escribe el CSV con las columnas y el orden exactos de la plantilla de Flowww.

| CSV | Origen | Notas |
|---|---|---|
| `clients.csv` | vista `clients` | Teléfonos normalizados (incluidos los que venían en notación científica), sexo, fechas en `dd/mm/aaaa` y clínica por defecto cuando falta. Mantuve a los empleados porque también eran clientes de la clínica. |
| `diary_gen.csv` | agenda futura | Profesional traducido con el mapeo de doctores; las citas sin profesional se asignan al doctor titular. |
| `budgets_gen.csv` | vista `budgets_gen` | Precio sin IVA y tratamientos traducidos a productos de la tarifa de Flowww. |
| `Clients_crm.csv` | `historiaclinica` y `fichamedica` | Historia clínica como comentarios del cliente. El texto venía con HTML, así que decodifico las entidades y elimino etiquetas y caracteres invisibles. |
| `deferred_uninvoiced.csv` | tabla `deudores` | Pagos aplazados pendientes. |
| `advances_gen.csv` | tabla `acreedores` | Anticipos del cliente. |
| `clients_tracking_gen.csv` y `diary_gen_hidden.csv` | vista `parametros_corporales` | Ver el apartado de estudios antropométricos. |
| `files.csv` y `pictures.csv` | tabla `multimedia` | Ver el apartado de ficheros. |

**Estudios antropométricos.** En Flowww cada seguimiento de medidas tiene que colgar de una cita. El origen no tenía esas citas, así que genero una cita invisible por cada seguimiento (`diary_gen_hidden.csv`) y alineo los tres identificadores (`TrackGDiaryID`, `DiaryID` y `DiaryGID`) para que encajen al cargarlos. Si un cliente tiene varias mediciones el mismo día, separo las citas 30 minutos entre sí. Cada seguimiento se convierte en varias filas: la fecha de lectura, los parámetros fijos (peso, talla, IMC, etc.), la parte del cuerpo y una fila por cada medida.

### 4. Ficheros y fotos

Fue la parte más delicada. Los ficheros físicos venían en una carpeta por cliente, pero las rutas registradas en la base de datos no siempre coincidían con lo que había en disco.

1. **Metadatos.** A partir de la tabla `multimedia` genero `files.csv` (documentos) y `pictures.csv` (imágenes), separados por extensión. Los ficheros sin extensión, o con una extensión solo numérica como `.20`, van a un CSV de auditoría para revisarlos a mano.
2. **Nombres con `/` dentro.** Algunos nombres de fichero contenían una barra como parte del texto, por ejemplo `(S/H)`. Al principio usaba `basename()` y esos nombres quedaban cortados. Lo corregí para conservar el nombre exactamente como viene de SQL, normalizado a Unicode NFC para no perder las tildes.
3. **Cuadrar con el disco.** El notebook `02_correccion_rutas_ficheros.ipynb` compara cada ruta con los ficheros reales de la carpeta del cliente. Si no hay coincidencia exacta, busca el fichero más parecido con `SequenceMatcher` y solo lo acepta por encima del 93 % de similitud. Genera el CSV corregido, una auditoría con la ruta original y la nueva, la lista de ficheros que no aparecen y la de duplicados eliminados.
4. **Prueba previa.** Antes de la carga completa hice una POC con 150 ficheros para validar el circuito de principio a fin.

### 5. Mapeos

Hay conceptos que no se pueden traducir solo con código porque dependen de cómo está configurada la clínica en Flowww:

- **Doctores:** cada profesional del origen se corresponde con un usuario de Flowww.
- **Tratamientos:** cada código de tratamiento (`product_map`) se corresponde con un producto o servicio de la tarifa de Flowww.
- **Producto "Migrado":** para las líneas de presupuesto con un tratamiento sin equivalencia, `obtener_id.py` crea (o recupera, si ya existe) un producto genérico llamado "Migrado". Así no se pierde ninguna línea y la clínica puede reasignarlas después.

Los ficheros de mapeo no están en el repositorio porque contienen la tarifa y los nombres del personal de la clínica.

### 6. Carga en MySQL

La carga la lanza `orchestrator.py`, que ejecuta los pasos en orden:

1. **Prueba de conexión** con la base de datos de destino.
2. **Backup y reset** (opcional): antes de vaciar las tablas de destino hago una copia de seguridad con `mysqldump`, para poder volver atrás si algo sale mal.
3. **Loaders**: recorre las entidades activas de `step01_config.py` en su orden y ejecuta el loader de cada una.

Todos los loaders siguen el mismo patrón:

- Vuelcan el CSV en una tabla de staging (`__mig_<entidad>`), sin tocar todavía las tablas reales.
- Traducen los identificadores de origen con las tablas de mapeo (`__mapping_users`, `__mapping_services`, `__mapping_products`, `__mapping_cabinets`) y con los catálogos de Flowww (`x_config_clinics`, `x_config_products_det`, etc.).
- Insertan en la tabla final con un `INSERT ... SELECT` desde staging y muestran por consola cuántas filas han entrado.

En ficheros y fotos, el loader numera cada registro a partir del último ID que ya existe en destino y genera un CSV con la ruta local y el nombre remoto de cada fichero (el ID con 9 dígitos más el nombre original). Con esa lista se copiaron los documentos y se convirtieron las fotos en el servidor de Flowww mediante scripts de PowerShell.

En `step01_config.py` se activa o desactiva cada entidad (`enabled`) y se define su orden. Eso me permitió cargar por partes, comprobar cada una y repetir solo lo que fallaba.

### 7. Verificación

Después de cada carga cuadré el número de registros de cada CSV con lo insertado en MySQL y preparé una batería de pruebas con clientes concretos (ficha, historia clínica, agenda, presupuestos, documentos y fotos) para revisarlos uno a uno en Flowww junto con la clínica.

## Volumen migrado

| Concepto | Registros |
|---|---|
| Clientes | 12.088 |
| Historia clínica (comentarios) | 47.906 |
| Agenda futura | 293 |
| Presupuestos (líneas) | 1.546 |
| Pagos aplazados | 77 |
| Anticipos | 18 |
| Seguimientos antropométricos (filas) | 32.816 |
| Citas invisibles para los seguimientos | 2.344 |
| Documentos | 10.696 |
| Fotos | 74.403 |

## Problemas que tuve que resolver

- **Identificadores.** El origen usa GUIDs y Flowww IDs numéricos. La tabla `person_dup` con un ID autonumérico me dio una clave única y estable para todas las relaciones.
- **Datos calculados.** Las deudas y los anticipos solo existían como resultado de un procedimiento almacenado. Tuve que leer su definición, ejecutarlos con los parámetros adecuados y persistir el resultado.
- **Texto con HTML.** La historia clínica guardaba texto enriquecido. Lo limpié para que se lea bien en Flowww sin perder contenido ni tildes.
- **Codificación.** Flowww trabaja en `latin1` y el origen en Unicode. Normalicé los textos antes de exportarlos para que no aparecieran caracteres extraños.
- **Rutas de ficheros.** Nombres con barras dentro, ficheros sin extensión y rutas que no coincidían con el disco. Lo resolví con el emparejamiento por similitud y auditorías de todo lo que no cuadraba, en lugar de descartarlo sin más.
- **Cargas repetibles.** Llegaron varias copias de la base de datos a lo largo del proyecto. Por eso los scripts SQL principales se pueden volver a ejecutar, los notebooks reescriben los CSV y la carga hace un backup antes de resetear.

## Cómo ejecutarlo

1. Restaurar el `.bak` en SQL Server y ejecutar los scripts de `01_extraccion/sql/`.
2. Copiar `.env.example` a `.env` y rellenar los datos de conexión.
3. Instalar las dependencias:
   ```
   pip install -r requirements.txt
   ```
4. Ejecutar los notebooks de `01_extraccion/notebooks/` para generar los CSV y corregir las rutas de los ficheros.
5. Copiar los CSV a la carpeta `input/` de `02_carga`, activar las entidades en `step01_config.py` y lanzar:
   ```
   python orchestrator.py
   ```

## Qué no está en el repositorio

Por protección de datos (son datos de salud), no he subido la copia de la base de datos, los CSV generados, los ficheros de los pacientes, los mapeos de la clínica ni los logs de las cargas. Las credenciales se leen de un `.env` que tampoco se sube. Las rutas y los nombres que aparecen en el código están anonimizados.


USE CLINICA_ORIGEN;
GO

-- Vistas/SP/funciones que mencionen "deud", "deuda", "pendiente", "moros", etc.
SELECT 
  o.type_desc,
  s.name AS schema_name,
  o.name AS object_name
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
JOIN sys.sql_modules m ON m.object_id = o.object_id
WHERE 
  m.definition LIKE '%deud%' OR
  m.definition LIKE '%deuda%' OR
  m.definition LIKE '%pend%' OR
  m.definition LIKE '%impag%' OR
  m.definition LIKE '%moros%' OR
  m.definition LIKE '%venc%'
ORDER BY o.type_desc, s.name, o.name;


----------------------------

/*Eso confirma lo que sospechábamos: “Deudores” en el sistema NO es una tabla, 
es un cálculo que el sistema expone vía procedimientos almacenados.*/


-- Aquí tienes los siguientes pasos para ver qué hace, qué tablas usa, y cómo sacar el listado.

USE CLINICA_ORIGEN;
GO

EXEC sp_help 'dbo.ObtenerDeudoresAcreedoresAFechaActual';
GO

EXEC sp_help 'dbo.ObtenerDeudoresAcreedoresAFinDeAnyo';
GO

-------------------------- Sacamos la tabla 

EXEC dbo.ObtenerDeudoresAcreedoresAFechaActual
  @codclinica = 1,
  @codunidad = -1,             -- TODAS
  @fecha_ini = '19000101',
  @fecha_end = '21000101',     -- ojo: el SP usa "< @fecha_end"
  @importe_mayor = NULL,       -- SIN FILTRO IMPORTE
  @importe_menor = NULL,       -- SIN FILTRO IMPORTE
  @codtipoespecialidad = -1,
  @codcomunicacion = -1,
  @morosos = 'Todos',
  @seguro = '-1',
  @pideDeudores = 1;


  -------------------- (Crar tabla física Deudores + SP “refresh”)

  /*Crea/asegura la tabla dbo.deudores (persistente, sin histórico)

Crea/actualiza el procedimiento dbo.sp_refresh_deudores

Ejecuta el refresh (1 click)

Te deja SELECT * FROM dbo.deudores

Importante: ajusta @codclinica si no es 1.*/

 USE CLINICA_ORIGEN;
GO

/* =========================================================
   1) Tabla final (persistente) dbo.deudores (sin histórico)
   ========================================================= */
IF OBJECT_ID('dbo.deudores', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.deudores (
        codpersona     varchar(36)  NOT NULL,
        personaID      int          NULL,
        nombre         varchar(200) NULL,
        apellido1      varchar(200) NULL,
        apellido2      varchar(200) NULL,
        ultimaVisita   varchar(20)  NULL,
        fechadeuda     varchar(20)  NULL,
        saldoclinica   varchar(50)  NULL,
        saldostring    varchar(50)  NULL,
        ultimoPago     varchar(20)  NULL,
        CONSTRAINT PK_deudores PRIMARY KEY (codpersona)
    );
END
GO

/* =========================================================
   2) SP de refresh (1 click)
   - TRUNCATE y recarga desde el SP origen
   - JOIN con persona_dup para traer personaID
   ========================================================= */
CREATE OR ALTER PROCEDURE dbo.sp_refresh_deudores
    @codclinica int = 1
AS
BEGIN
    SET NOCOUNT ON;

    -- Limpia tabla final (sin histórico)
    TRUNCATE TABLE dbo.deudores;

    -- Tabla staging temporal con las columnas que nos interesan del SP
    CREATE TABLE #deudores_stg (
        codpersona     varchar(36)  NOT NULL,
        nombre         varchar(200) NULL,
        apellido1      varchar(200) NULL,
        apellido2      varchar(200) NULL,
        ultimaVisita   varchar(20)  NULL,
        fechadeuda     varchar(20)  NULL,
        saldoclinica   varchar(50)  NULL,
        saldostring    varchar(50)  NULL,
        ultimoPago     varchar(20)  NULL
    );

    -- Insertar desde el SP de origen (ojo: -1 = todas las unidades, importes NULL = sin filtro)
    INSERT INTO #deudores_stg (codpersona, nombre, apellido1, apellido2, ultimaVisita, fechadeuda, saldoclinica, saldostring, ultimoPago)
    EXEC dbo.ObtenerDeudoresAcreedoresAFechaActual
        @codclinica = @codclinica,
        @codunidad = -1,
        @fecha_ini = '19000101',
        @fecha_end = '21000101',   -- el SP usa "< @fecha_end"
        @importe_mayor = NULL,
        @importe_menor = NULL,
        @codtipoespecialidad = -1,
        @codcomunicacion = -1,
        @morosos = 'Todos',
        @seguro = '-1',
        @pideDeudores = 1;

    -- Cargar tabla final con JOIN a persona_dup
    INSERT INTO dbo.deudores (codpersona, personaID, nombre, apellido1, apellido2, ultimaVisita, fechadeuda, saldoclinica, saldostring, ultimoPago)
    SELECT
        d.codpersona,
        pd.personID,
        d.nombre,
        d.apellido1,
        d.apellido2,
        d.ultimaVisita,
        d.fechadeuda,
        d.saldoclinica,
        d.saldostring,
        d.ultimoPago
    FROM #deudores_stg d
    LEFT JOIN dbo.person_dup pd
        ON pd.codpersona = d.codpersona;  -- codpersona es GUID alfanumérico en ambos (según tu caso)

    DROP TABLE #deudores_stg;
END
GO

/* =========================================================
   3) Ejecutar refresh (1 click real)
   ========================================================= */
EXEC dbo.sp_refresh_deudores @codclinica = 1;
GO

/* =========================================================
   4) Ver resultado
   ========================================================= */
SELECT *
FROM dbo.deudores
-- ORDER BY TRY_CONVERT(int, NULLIF(codpersona, '')); -- si codpersona no es numérico, este ORDER BY no afecta; puedes quitarlo
GO


-- al llegar BBDD nueva ejecutar solo:

EXEC dbo.sp_refresh_deudores;
SELECT * FROM dbo.deudores;
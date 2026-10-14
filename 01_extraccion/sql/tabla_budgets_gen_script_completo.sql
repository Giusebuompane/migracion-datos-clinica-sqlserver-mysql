/* =========================================================
   SCRIPT ÚNICO (EJECUTAR EN SSMS DE UN SOLO CLICK)
   - CLINICA_ORIGEN
   - product_map + budget_map + vista dbo.budgets_gen
   ========================================================= */

USE CLINICA_ORIGEN;
GO

/* =========================================================
   0) LIMPIEZA PARA RE-EJECUCIÓN
   ========================================================= */
IF OBJECT_ID('dbo.budgets_gen', 'V') IS NOT NULL
    DROP VIEW dbo.budgets_gen;
GO

IF OBJECT_ID('dbo.budget_map', 'U') IS NOT NULL
    DROP TABLE dbo.budget_map;
GO

IF OBJECT_ID('dbo.product_map', 'U') IS NOT NULL
    DROP TABLE dbo.product_map;
GO


/* =========================================================
   1) TABLA product_map
   ========================================================= */
CREATE TABLE dbo.product_map (
    ProductID   INT IDENTITY(1,1) PRIMARY KEY,
    codigotrat  NVARCHAR(50) NOT NULL UNIQUE
);
GO


/* =========================================================
   2) POBLAR product_map con códigos únicos (sin nulos/vacíos/0)
   ========================================================= */
WITH cte AS (
    SELECT
        codigotrat,
        ROW_NUMBER() OVER (
            PARTITION BY codigotrat
            ORDER BY codigotrat
        ) AS rn
    FROM dbo.tratamientos
    WHERE codigotrat IS NOT NULL
      AND LTRIM(RTRIM(codigotrat)) <> ''
      AND LTRIM(RTRIM(codigotrat)) <> '0'
)
INSERT INTO dbo.product_map (codigotrat)
SELECT codigotrat
FROM cte
WHERE rn = 1;
GO

-- 3) Comprobación rápida product_map
SELECT TOP (50) * FROM dbo.product_map ORDER BY ProductID;
GO


/* =========================================================
   4) TABLA budget_map (mapeo de presupuestos)
   ========================================================= */
CREATE TABLE dbo.budget_map (
    BudgetGID        INT IDENTITY(1,1) PRIMARY KEY,
    codempresa       INT NOT NULL,
    codpersona       UNIQUEIDENTIFIER NOT NULL,
    codclinica       INT NOT NULL,
    codunidad        INT NOT NULL,
    codnumdocumento  INT NOT NULL
);
GO


/* =========================================================
   5) POBLAR budget_map (evitar GUID nulo / GUID cero)
   ========================================================= */
INSERT INTO dbo.budget_map (
    codempresa,
    codpersona,
    codclinica,
    codunidad,
    codnumdocumento
)
SELECT
    codempresa,
    codpersona,
    codclinica,
    codunidad,
    codnumdocumento
FROM dbo.presupuesto
WHERE codpersona IS NOT NULL
  AND codpersona <> '00000000-0000-0000-0000-000000000000';
GO


/* =========================================================
   6) COMPROBACIONES budget_map
   ========================================================= */
SELECT COUNT(*) AS PresupuestoTotal FROM dbo.presupuesto;
SELECT COUNT(*) AS BudgetMapTotal  FROM dbo.budget_map;

SELECT TOP (50) * FROM dbo.budget_map ORDER BY BudgetGID;
GO


/* =========================================================
   7) VISTA FINAL dbo.budgets_gen (VERSIÓN CORRECTA FINAL)
   ========================================================= */
CREATE OR ALTER VIEW dbo.budgets_gen AS
SELECT
    -- =========================
    -- Identificadores
    -- =========================

    -- 🔥 BudgetGID LÓGICO (1,2,3...) SIN TOCAR EL REAL
    DENSE_RANK() OVER (
        ORDER BY bm.BudgetGID
    ) AS BudgetGID,

    -- 🔥 BudgetID CONTADOR SIMPLE DE FILAS (1,2,3,4...)
    ROW_NUMBER() OVER (
        ORDER BY (SELECT NULL)
    ) AS BudgetID,

    -- =========================
    -- Relaciones
    -- =========================
    COALESCE(pm.ProductID, 1466) AS BudgetProductID,
    cli.personaID                AS BudgetClientID,
    prof.personaID               AS BudgetDoctorID,

    -- =========================
    -- Estado del presupuesto
    -- =========================
    CASE LTRIM(RTRIM(p.aceptado))
        WHEN 'AC' THEN 1      -- Aceptado
        WHEN 'DE' THEN 2      -- Denegado
        WHEN 'NA' THEN 2      -- No aceptado
        WHEN 'PR' THEN 0      -- Pendiente
        ELSE 0
    END AS BudgetGStatus,

    -- =========================
    -- Paciente
    -- =========================
    cli.nombre              AS ClientName,
    cli.apellido1           AS ClientSurname1,
    cli.apellido2           AS ClientSurname2,

    -- =========================
    -- Médico
    -- =========================
    prof.nombre             AS DoctorName,
    prof.apellido1          AS DoctorSurname1,
    prof.apellido2          AS DoctorSurname2,

    -- =========================
    -- Detalle presupuesto
    -- =========================
    dp.codunidad            AS BudgetUnits,
    dp.descripcion          AS BudgetComments,
    dp.importebi              AS BudgetPrice,
    dp.importedescuento     AS BudgetDiscount,
    dp.fechacreacion        AS BudgetCreateDate

FROM dbo.detallepresupuesto dp

LEFT JOIN dbo.presupuesto p
    ON p.codempresa      = dp.codempresa
   AND p.codpersona      = dp.codpersona
   AND p.codclinica      = dp.codclinica
   AND p.codunidad       = dp.codunidad
   AND p.codnumdocumento = dp.codnumdocumento

LEFT JOIN dbo.budget_map bm
    ON bm.codempresa      = dp.codempresa
   AND bm.codpersona      = dp.codpersona
   AND bm.codclinica      = dp.codclinica
   AND bm.codunidad       = dp.codunidad
   AND bm.codnumdocumento = dp.codnumdocumento

LEFT JOIN dbo.product_map pm
    ON pm.codigotrat = dp.codigotrat

LEFT JOIN dbo.person_dup cli
    ON cli.codpersona = dp.codpersona
   AND cli.codempresa = dp.codempresa

LEFT JOIN dbo.person_dup prof
    ON prof.codpersona = dp.codprofesional
   AND prof.codempresa = dp.codempresa;
GO


/* =========================================================
   8) TEST FINAL
   ========================================================= */
SELECT TOP (200) *
FROM dbo.budgets_gen
ORDER BY BudgetGID, BudgetID;
GO

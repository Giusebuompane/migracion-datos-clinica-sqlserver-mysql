USE CLINICA_ORIGEN;
GO

CREATE OR ALTER PROCEDURE dbo.sp_refresh_deudores
AS
BEGIN
  SET NOCOUNT ON;

  ----------------------------------------------------------------------
  -- 1) DROP + CREATE tabla final (sin histórico)
  ----------------------------------------------------------------------
  IF OBJECT_ID('dbo.deudores','U') IS NOT NULL
  BEGIN
    DROP TABLE dbo.deudores;
  END;

  CREATE TABLE dbo.deudores (
    personaID          int NULL,                -- solo de dbo.person_dup

    -- Todas las columnas del SP
    multiselect        varchar(max) NULL,
    codmodoenvio       int NULL,
    codnumpersona      varchar(max) NULL,
    codDeuAcre         varchar(max) NULL,
    codempresa         varchar(max) NULL,
    codpersona         varchar(36) NOT NULL,
    nombre             varchar(max) NULL,
    apellido1          varchar(max) NULL,
    apellido2          varchar(max) NULL,
    telefono           varchar(max) NULL,
    movil              varchar(max) NULL,
    email              varchar(max) NULL,
    dnicif             varchar(max) NULL,
    direccion          varchar(max) NULL,
    moroso             int NULL,
    morosostring       varchar(max) NULL,
    imprimir           int NULL,
    imprimirstring     varchar(max) NULL,
    ultimaVisita       varchar(max) NULL,
    proximaCita        varchar(max) NULL,
    codidioma          int NULL,
    fechadeudadatetime datetime NULL,
    fechadeuda         varchar(max) NULL,
    saldoclinica       varchar(max) NULL,
    saldostring        varchar(max) NULL,
    ultimoPago         varchar(max) NULL
  );

  ----------------------------------------------------------------------
  -- 2) Staging: mismas columnas que devuelve el SP
  ----------------------------------------------------------------------
  CREATE TABLE #deudores_full (
    multiselect        varchar(max) NULL,
    codmodoenvio       int NULL,
    codnumpersona      varchar(max) NULL,
    codDeuAcre         varchar(max) NULL,
    codempresa         varchar(max) NULL,
    codpersona         varchar(36) NOT NULL,
    nombre             varchar(max) NULL,
    apellido1          varchar(max) NULL,
    apellido2          varchar(max) NULL,
    telefono           varchar(max) NULL,
    movil              varchar(max) NULL,
    email              varchar(max) NULL,
    dnicif             varchar(max) NULL,
    direccion          varchar(max) NULL,
    moroso             int NULL,
    morosostring       varchar(max) NULL,
    imprimir           int NULL,
    imprimirstring     varchar(max) NULL,
    ultimaVisita       varchar(max) NULL,
    proximaCita        varchar(max) NULL,
    codidioma          int NULL,
    fechadeudadatetime datetime NULL,
    fechadeuda         varchar(max) NULL,
    saldoclinica       varchar(max) NULL,
    saldostring        varchar(max) NULL,
    ultimoPago         varchar(max) NULL
  );

  INSERT INTO #deudores_full
  EXEC dbo.ObtenerDeudoresAcreedoresAFechaActual
    @codclinica = 1,
    @codunidad = -1,
    @fecha_ini = '19000101',
    @fecha_end = '21000101',
    @importe_mayor = NULL,
    @importe_menor = NULL,
    @codtipoespecialidad = -1,
    @codcomunicacion = -1,
    @morosos = 'Todos',
    @seguro = '-1',
    @pideDeudores = 1;

  ----------------------------------------------------------------------
  -- 3) Insert final: todas columnas del SP + personaID
  ----------------------------------------------------------------------
  INSERT INTO dbo.deudores (
    personaID,
    multiselect, codmodoenvio, codnumpersona, codDeuAcre, codempresa, codpersona,
    nombre, apellido1, apellido2, telefono, movil, email, dnicif, direccion,
    moroso, morosostring, imprimir, imprimirstring, ultimaVisita, proximaCita,
    codidioma, fechadeudadatetime, fechadeuda, saldoclinica, saldostring, ultimoPago
  )
  SELECT
    pd.personaID,
    f.multiselect, f.codmodoenvio, f.codnumpersona, f.codDeuAcre, f.codempresa, f.codpersona,
    f.nombre, f.apellido1, f.apellido2, f.telefono, f.movil, f.email, f.dnicif, f.direccion,
    f.moroso, f.morosostring, f.imprimir, f.imprimirstring, f.ultimaVisita, f.proximaCita,
    f.codidioma, f.fechadeudadatetime, f.fechadeuda, f.saldoclinica, f.saldostring, f.ultimoPago
  FROM #deudores_full f
  LEFT JOIN dbo.person_dup pd
    ON pd.codpersona = f.codpersona;

  DROP TABLE #deudores_full;
END
GO

-- Ejecutar refresh + ver tabla
EXEC dbo.sp_refresh_deudores;
SELECT * FROM dbo.deudores;
GO
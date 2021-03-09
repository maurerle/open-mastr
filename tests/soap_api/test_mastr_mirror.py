import datetime
import pytest
import pytz

from open_mastr.data_io import read_csv_data
from open_mastr.soap_api.mirror import MaStRMirror
from open_mastr.soap_api import orm
from open_mastr.utils.helpers import session_scope


TECHNOLOGIES = ["wind", "hydro", "solar", "biomass", "combustion", "nuclear", "gsgk", "storage"]
DATA_TYPES = ["unit_data", "eeg_data", "kwk_data", "permit_data"]
LIMIT = 1
DATE = datetime.datetime(2020, 11, 27, 0, 0, 0)


@pytest.fixture
def mastr_mirror():
    mastr_mirror_instance = MaStRMirror(
        initialize_db=True,
        parallel_processes=2
    )

    return mastr_mirror_instance


@pytest.mark.dependency(name="backfill_basic")
def test_backfill_basic(mastr_mirror):
    mastr_mirror.backfill_basic(technology=TECHNOLOGIES,
                                date=DATE,
                                limit=LIMIT)

    # The table basic_units should have at least as much rows as TECHNOLOGIES were queried
    with session_scope() as session:
        response = session.query(orm.BasicUnit).count()
        assert response >= len(TECHNOLOGIES)


@pytest.mark.dependency(depends=["backfill_basic"], name="retrieve_additional_data")
def test_retrieve_additional_data(mastr_mirror):
    for tech in TECHNOLOGIES:
        for data_type in DATA_TYPES:
            mastr_mirror.retrieve_additional_data(
                technology=tech,
                data_type=data_type
            )

    # This comparison currently fails because of
    # https://github.com/OpenEnergyPlatform/open-MaStR/issues/154
    # with session_scope() as session:
    #     for tech in TECHNOLOGIES:
    #         mapper = getattr(orm, mastr_mirror.orm_map[tech]["unit_data"])
    #         response = session.query(mapper).count()
    #         assert response >= LIMIT

@pytest.mark.dependency(depends=["retrieve_additional_data"], name="update_latest")
def test_update_latest(mastr_mirror):
    mastr_mirror.backfill_basic(technology=TECHNOLOGIES,
                                date="latest",
                                limit=LIMIT)

    # Test if latest date is newer that intially requested data in backfill_basic
    with session_scope() as session:
        response = session.query(orm.BasicUnit.DatumLetzeAktualisierung).order_by(
            orm.BasicUnit.DatumLetzeAktualisierung.desc()).first()
    assert response.DatumLetzeAktualisierung > pytz.utc.localize(DATE)

@pytest.mark.dependency(depends=["update_latest"], name="create_additional_data_requests")
def test_create_additional_data_requests(mastr_mirror):
    with session_scope() as session:
        for tech in TECHNOLOGIES:
            session.query(orm.AdditionalDataRequested).filter_by(technology="gsgk").delete()
            session.commit()
            mastr_mirror.create_additional_data_requests(tech, data_types=DATA_TYPES)


@pytest.mark.dependency(depends=["create_additional_data_requests"], name="export_to_csv")
def test_to_csv(mastr_mirror):
    for tech in TECHNOLOGIES:
        mastr_mirror.to_csv(technology=tech,
                            additional_data=DATA_TYPES,
                            statistic_flag=None
                            )
    # Test if all EinheitMastrNummer in basic_units are included in CSV file
    with session_scope() as session:
        raw_data = read_csv_data("raw")
        for tech, df in raw_data.items():
            units = session.query(orm.BasicUnit.EinheitMastrNummer).filter(
                orm.BasicUnit.Einheittyp == mastr_mirror.unit_type_map_reversed[tech])
            for unit in units:
                assert unit.EinheitMastrNummer in df.index

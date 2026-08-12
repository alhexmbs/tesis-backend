import pandas as pd
import requests


def get_data_from_bcrp(cod, start_date, end_date):
    # cod format -> PN40408PM
    # start_date format -> 2010-1 (same end_date)
    url = f"https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{cod}/json/{start_date}/{end_date}/esp"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        periods = data.get("periods", [])

        fechas = [item["name"] for item in periods]

        indices = []
        for period in periods:
            indice_str = period["values"][0]
            if indice_str == "n.d.":
                indices.append(None)
            else:
                indices.append(float(indice_str))

        df_indices = pd.DataFrame({"fecha": fechas, "indice_precio": indices})

        meses = {
            "Ene": "01",
            "Feb": "02",
            "Mar": "03",
            "Abr": "04",
            "May": "05",
            "Jun": "06",
            "Jul": "07",
            "Ago": "08",
            "Sep": "09",
            "Oct": "10",
            "Nov": "11",
            "Dic": "12",
        }

        df_indices[["mes_str", "anio"]] = df_indices["fecha"].str.split(
            ".", expand=True
        )
        df_indices["mes_num"] = df_indices["mes_str"].map(meses)  # type: ignore
        df_indices["fecha"] = pd.to_datetime(
            df_indices["anio"] + "-" + df_indices["mes_num"] + "-01"
        )

        df_indices = (
            df_indices.loc[:, ["fecha", "indice_precio"]]
            .sort_values(by="fecha")
            .reset_index(drop=True)
        )

        return df_indices

    else:
        print(f"Error al conectar con BCRP: Código {response.status_code}")
        return None

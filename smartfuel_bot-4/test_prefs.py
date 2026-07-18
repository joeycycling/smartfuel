from prefs_loader import load_preferences_from_csv

SAMPLE_CSV = '''Timestamp,Nombre Completo,Email,País/ciudad de residencia,¿Entrenas con medidor de potencia?,¿Que deportes practicas?,¿Cual es tu horario de entreno?,¿Qué tan sedentario o activo es tu día fuera del entreno?,¿Tienes alguna alergia o intolerancia alimenticia?,¿Sigues alguna dieta particular?,¿Hay alimentos que NO consumes por preferencia personal?,¿Qué proteínas sí comes?,¿Qué carbohidratos prefieres?,¿Qué lácteos consumes?,¿Cuáles son tus frutas favoritas?,¿Consumes alcohol regularmente?,¿Prefieres variedad en tus comidas o repetir lo mismo varios días?,¿Usas proteína en polvo?,"Si respondiste sí, ¿marca/sabor de tu proteína?",¿Usas isotónico o bebida deportiva específica?,"Si respondiste sí, ¿marca/sabor de tu bebida deportiva?",¿Cuántas comidas prefieres al día?,¿Cocinas tú o alguien cocina por ti?,¿Cuánto tiempo tienes disponible para preparar tus comidas en un día típico?,¿Qué restaurantes o cadenas de comida rápida frecuentas?,¿Qué sueles pedir en esos lugares?,¿Hay algún restaurante que definitivamente evitas?,¿Hay algo más sobre tu alimentación o relación con la comida que el coach deba saber?,TRAININGPEAKS ID
7/6/2026 20:48:23,joey marti,joeymmarti@gmail.com,republica dominicana,Si,"Ciclismo, GYM",Madrugada,Trabajo de escritorio,Mariscos,Ninguna,aguacate,"Pollo, Res, Cerdo, Salmón / pescado, Huevos, Embutidos (jamón, salchicha, salami), Atún, Pavo","Arroz blanco, Papa, Avena, Pasta, Pan, Tortilla, Guineo / plátano","Queso feta, Queso ricotta, Queso de freír, Leche de almendra","Piña, Guineo",No,Prefiero variedad,Si,iso100,Si,gatorade,3 comidas,Yo cocino,Moderado,todas las franquicias ,pechugas y alguna proteina conjunta con arroz ,,,
'''

if __name__ == "__main__":
    parsed = load_preferences_from_csv(SAMPLE_CSV)[0]
    for k, v in parsed.items():
        print(f"{k}: {v}")

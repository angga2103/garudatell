from flask import jsonify

def success(data=None,message="OK"):

    return jsonify({
        "status":True,
        "message":message,
        "data":data
    })

def error(message="ERROR",code=400):

    return jsonify({
        "status":False,
        "message":message
    }),code

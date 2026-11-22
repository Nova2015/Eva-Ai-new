// Frontend/src/components/SecurityStatus.js

import React from "react";

const SecurityStatus = ({ status }) => {

    const getStatusColor = () => {

        switch (status) {

            case "SAFE":
                return "green";

            case "LOW":
                return "orange";

            case "HIGH":
                return "red";

            case "CRITICAL":
                return "darkred";

            default:
                return "gray";
        }
    };

    return (

        <div
            style={{
                padding: "20px",
                borderRadius: "10px",
                background: "#111",
                color: "#fff",
                marginBottom: "20px"
            }}
        >

            <h2>AI Security Status</h2>

            <div
                style={{
                    width: "120px",
                    padding: "10px",
                    borderRadius: "8px",
                    background: getStatusColor(),
                    textAlign: "center",
                    fontWeight: "bold"
                }}
            >
                {status}
            </div>

        </div>
    );
};

export default SecurityStatus;